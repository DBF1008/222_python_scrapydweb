# coding: utf-8
from datetime import datetime
import glob
import io
import os
from pprint import pformat
import re
from shutil import copyfile, copyfileobj, rmtree
from subprocess import CalledProcessError
import tarfile
import tempfile
import time
import zipfile

from flask import flash, redirect, render_template, request, url_for
from six import text_type
from six.moves.configparser import Error as ScrapyCfgParseError
from werkzeug.utils import secure_filename

from ...vars import PY2
from ..baseview import BaseView
from .scrapyd_deploy import _build_egg, get_config
from .utils import mkdir_p, slot


SCRAPY_CFG = """
[settings]
default = projectname.settings

[deploy]
url = http://localhost:6800/
project = projectname

"""
folder_project_dict = {}

# Bit 11 of the ZIP general purpose bit flag: filename is UTF-8 encoded (EFS).
ZIP_UTF8_FLAG = 0x800


def normalize_pathname(name):
    # Guarantee a surrogate-free, UTF-8 encodable str so that the path can be
    # walked, joined, displayed (flash/template) and logged without raising
    # UnicodeEncodeError later on. A lone surrogate (e.g. from os.walk reading
    # an undecodable on-disk name) is replaced with '?'.
    if PY2 or not isinstance(name, text_type):
        return name
    try:
        name.encode('utf-8')
    except UnicodeEncodeError:
        name = name.encode('utf-8', 'replace').decode('utf-8')
    return name


def decode_zip_member_filename(filename, flag_bits):
    # In PY3, zipfile decodes a member name as UTF-8 only when the EFS/UTF-8 flag
    # (bit 11) is set; otherwise it falls back to cp437, which turns non-ASCII
    # names (e.g. a zip packaged on Windows with cp936/gbk, or even on macOS
    # which stores UTF-8 bytes without setting the flag) into mojibake. Recover
    # the original bytes and try the common encodings so that Chinese / nested
    # project directories keep usable names. Always return a surrogate-free path.
    if PY2 or not isinstance(filename, text_type):
        return filename
    if not (flag_bits & ZIP_UTF8_FLAG):
        try:
            raw = filename.encode('cp437')  # reverse zipfile's cp437 fallback
        except UnicodeEncodeError:
            raw = filename.encode('utf-8', 'surrogateescape')
        # Try UTF-8 first (macOS/Linux often omit the flag while storing UTF-8);
        # gbk bytes are invalid UTF-8 and correctly fall through to gbk.
        for encoding in ('utf-8', 'gbk'):
            try:
                filename = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    return normalize_pathname(filename)


def extract_zip_to_dir(zip_file, tmpdir):
    # Extract a ZipFile member by member instead of using extractall() so that a
    # single illegal/undecodable name cannot abort the whole archive, and so each
    # name is recovered + normalized to a filesystem-safe path. Leading/parent
    # path components are stripped to keep extraction confined to tmpdir (zip
    # slip). Returns a list of (member_name, error) tuples for skipped members.
    skipped = []
    for zip_info in zip_file.infolist():
        original = zip_info.filename
        filename = decode_zip_member_filename(original, zip_info.flag_bits)
        parts = [p for p in filename.replace('\\', '/').split('/')
                 if p not in ('', os.curdir, os.pardir)]
        if not parts:
            continue
        target = os.path.join(tmpdir, *parts)
        is_dir = filename.endswith('/') or original.endswith('/')
        if not is_dir:
            try:
                is_dir = zip_info.is_dir()  # ZipInfo.is_dir() is PY3.6+ only
            except AttributeError:
                pass
        try:
            if is_dir:
                mkdir_p(target)
            else:
                # zipfile from Windows "send to compressed folder" may yield the
                # inner file before its folder entry, so create parents on demand.
                mkdir_p(os.path.dirname(target) or tmpdir)
                with io.open(target, 'wb') as f_out:
                    copyfileobj(zip_file.open(zip_info), f_out)
        except (IOError, OSError) as err:
            skipped.append((original, str(err)))
    return skipped


def walk_for_scrapy_cfg(search_path, walk=os.walk):
    # Walk search_path top-down and return (scrapy_cfg_path, searched_paths) for
    # the shallowest directory that contains a scrapy.cfg, so that a zip with a
    # nested project directory still resolves to a valid project root. The
    # searched paths are sanitized for safe display even if walk yields a name
    # carrying surrogates.
    searched_paths = []
    for dirpath, dirnames, filenames in walk(search_path):
        searched_paths.append(normalize_pathname(os.path.abspath(dirpath)))
        scrapy_cfg_path = os.path.abspath(os.path.join(dirpath, 'scrapy.cfg'))
        if os.path.exists(scrapy_cfg_path):
            return scrapy_cfg_path, searched_paths
    return '', searched_paths


class DeployView(BaseView):

    def __init__(self):
        super(DeployView, self).__init__()

        self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVER, 'addversion')
        self.template = 'scrapydweb/deploy.html'

        self.scrapy_cfg_list = []
        self.project_paths = []
        self.folders = []
        self.projects = []
        self.modification_times = []
        self.latest_folder = ''

    def dispatch_request(self, **kwargs):
        self.set_scrapy_cfg_list()
        self.project_paths = [os.path.dirname(i) for i in self.scrapy_cfg_list]
        self.folders = [os.path.basename(i) for i in self.project_paths]
        self.get_modification_times()
        self.parse_scrapy_cfg()

        kwargs = dict(
            node=self.node,
            url=self.url,
            url_projects=url_for('projects', node=self.node),
            selected_nodes=self.get_selected_nodes(),
            folders=self.folders,
            projects=self.projects,
            modification_times=self.modification_times,
            latest_folder=self.latest_folder,
            SCRAPY_PROJECTS_DIR=self.SCRAPY_PROJECTS_DIR.replace('\\', '/'),
            url_servers=url_for('servers', node=self.node, opt='deploy'),
            url_deploy_upload=url_for('deploy.upload', node=self.node)
        )
        return render_template(self.template, **kwargs)

    def set_scrapy_cfg_list(self):
        # Python 'ascii' codec can't decode byte
        try:
            self.scrapy_cfg_list = glob.glob(os.path.join(self.SCRAPY_PROJECTS_DIR, '*', u'scrapy.cfg'))
        except UnicodeDecodeError:
            if PY2:
                for name in os.listdir(os.path.join(self.SCRAPY_PROJECTS_DIR, u'')):
                    if not isinstance(name, text_type):
                        msg = "Ignore non-unicode filename %s in %s" % (repr(name), self.SCRAPY_PROJECTS_DIR)
                        self.logger.error(msg)
                        flash(msg, self.WARN)
                    else:
                        scrapy_cfg = os.path.join(self.SCRAPY_PROJECTS_DIR, name, u'scrapy.cfg')
                        if os.path.exists(scrapy_cfg):
                            self.scrapy_cfg_list.append(scrapy_cfg)
            else:
                raise
        # '/home/username/Downloads/scrapydweb/scrapydweb/data/demo_projects/\udc8b\udc8billegal/scrapy.cfg'
        # UnicodeEncodeError: 'utf-8' codec can't encode characters in position 64-65: surrogates not allowed
        new_scrapy_cfg_list = []
        for scrapy_cfg in self.scrapy_cfg_list:
            try:
                scrapy_cfg.encode('utf-8')
            except UnicodeEncodeError:
                msg = "Ignore scrapy.cfg in illegal pathname %s" % repr(os.path.dirname(scrapy_cfg))
                self.logger.error(msg)
                flash(msg, self.WARN)
            else:
                new_scrapy_cfg_list.append(scrapy_cfg)
        self.scrapy_cfg_list = new_scrapy_cfg_list

        self.scrapy_cfg_list.sort(key=lambda x: x.lower())

    def get_modification_times(self):
        timestamps = [self.get_modification_time(path) for path in self.project_paths]
        self.modification_times = [datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H_%M_%S') for ts in timestamps]

        if timestamps:
            max_timestamp_index = timestamps.index(max(timestamps))
            self.latest_folder = self.folders[max_timestamp_index]
            self.logger.debug('latest_folder: %s', self.latest_folder)

    def get_modification_time(self, path, func_walk=os.walk, retry=True):
        # https://stackoverflow.com/a/29685234/10517783
        # https://stackoverflow.com/a/13454267/10517783
        filepath_list = []
        in_top_dir = True
        try:
            for dirpath, dirnames, filenames in func_walk(path):
                if in_top_dir:
                    in_top_dir = False
                    dirnames[:] = [d for d in dirnames if d not in ['build', 'project.egg-info']]
                    filenames = [f for f in filenames
                                 if not (f.endswith('.egg') or f in ['setup.py', 'setup_backup.py'])]
                for filename in filenames:
                    filepath_list.append(os.path.join(dirpath, filename))
        except UnicodeDecodeError:
            msg = "Found illegal filenames in %s" % path
            self.logger.error(msg)
            flash(msg, self.WARN)
            if PY2 and retry:
                return self.get_modification_time(path, func_walk=self.safe_walk, retry=False)
            else:
                raise
        else:
            return max([os.path.getmtime(f) for f in filepath_list] or [time.time()])

    def parse_scrapy_cfg(self):
        for (idx, scrapy_cfg) in enumerate(self.scrapy_cfg_list):
            folder = self.folders[idx]
            key = '%s (%s)' % (folder, self.modification_times[idx])

            project = folder_project_dict.get(key, '')
            if project:
                self.projects.append(project)
                self.logger.debug('Hit %s, project %s', key, project)
                continue
            else:
                project = folder
                try:
                    # lib/configparser.py: def get(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
                    # projectname/scrapy.cfg: [deploy] project = demo
                    # PY2: get() got an unexpected keyword argument 'fallback'
                    # project = get_config(scrapy_cfg).get('deploy', 'project', fallback=folder) or folder
                    project = get_config(scrapy_cfg).get('deploy', 'project')
                except ScrapyCfgParseError as err:
                    self.logger.error("%s parse error: %s", scrapy_cfg, err)
                finally:
                    project = project or folder
                    self.projects.append(project)
                    folder_project_dict[key] = project
                    self.logger.debug('Add %s, project %s', key, project)

        keys_all = list(folder_project_dict.keys())
        keys_exist = ['%s (%s)' % (_folder, _modification_time)
                      for (_folder, _modification_time) in zip(self.folders, self.modification_times)]
        diff = set(keys_all).difference(set(keys_exist))
        for key in diff:
            self.logger.debug('Pop %s, project %s', key, folder_project_dict.pop(key))
        self.logger.debug(self.json_dumps(folder_project_dict))
        self.logger.debug('folder_project_dict length: %s', len(folder_project_dict))


class DeployUploadView(BaseView):
    methods = ['POST']

    def __init__(self):
        super(DeployUploadView, self).__init__()

        self.url = ''
        self.template = 'scrapydweb/deploy_results.html'

        self.folder = ''
        self.project = ''
        self.version = ''
        self.selected_nodes_amount = 0
        self.selected_nodes = []
        self.first_selected_node = 0

        self.eggname = ''
        self.eggpath = ''
        self.scrapy_cfg_path = ''
        self.scrapy_cfg_searched_paths = []
        self.scrapy_cfg_not_found = False
        self.scrapy_cfg_parse_error = ''
        self.build_egg_subprocess_error = ''
        self.data = None
        self.js = {}

        self.slot = slot

    def dispatch_request(self, **kwargs):
        self.handle_form()

        if self.scrapy_cfg_not_found or self.scrapy_cfg_parse_error or self.build_egg_subprocess_error:
            if self.selected_nodes_amount > 1:
                alert = "Multinode deployment terminated:"
            else:
                alert = "Fail to deploy project:"

            if self.scrapy_cfg_not_found:
                text = "scrapy.cfg not found"
                tip = "Make sure that the 'scrapy.cfg' file resides in your project directory. "
            elif self.scrapy_cfg_parse_error:
                text = self.scrapy_cfg_parse_error
                tip = "Check the content of the 'scrapy.cfg' file in your project directory. "
            else:
                text = self.build_egg_subprocess_error
                tip = ("Check the content of the 'scrapy.cfg' file in your project directory. "
                       "Or build the egg file by yourself instead. ")

            if self.scrapy_cfg_not_found:
                # Handle case when scrapy.cfg not found in zip file which contains illegal pathnames in PY3
                message = "scrapy_cfg_searched_paths:\n%s" % pformat(self.scrapy_cfg_searched_paths)
            else:
                message = "# The 'scrapy.cfg' file in your project directory should be like:\n%s" % SCRAPY_CFG

            return render_template(self.template_fail, node=self.node,
                                   alert=alert, text=text, tip=tip, message=message)
        else:
            self.prepare_data()
            status_code, self.js = self.make_request(self.url, data=self.data, auth=self.AUTH)

        if self.js['status'] != self.OK:
            # With multinodes, would try to deploy to the first selected node first
            if self.selected_nodes_amount > 1:
                alert = ("Multinode deployment terminated, "
                         "since the first selected node returned status: " + self.js['status'])
            else:
                alert = "Fail to deploy project, got status: " + self.js['status']
            message = self.js.get('message', '')
            if message:
                self.js['message'] = 'See details below'

            return render_template(self.template_fail, node=self.node,
                                   alert=alert, text=self.json_dumps(self.js), message=message)
        else:
            if self.selected_nodes_amount == 0:
                return redirect(url_for('schedule', node=self.node,
                                        project=self.project, version=self.version))
            else:
                kwargs = dict(
                    node=self.node,
                    selected_nodes=self.selected_nodes,
                    first_selected_node=self.first_selected_node,
                    js=self.js,
                    project=self.project,
                    version=self.version,
                    url_projects_first_selected_node=url_for('projects', node=self.first_selected_node),
                    url_projects_list=[url_for('projects', node=n) for n in range(1, self.SCRAPYD_SERVERS_AMOUNT + 1)],
                    url_xhr=url_for('deploy.xhr', node=self.node, eggname=self.eggname,
                                    project=self.project, version=self.version),
                    url_schedule=url_for('schedule', node=self.node, project=self.project,
                                         version=self.version),
                    url_servers=url_for('servers', node=self.node, opt='schedule', project=self.project,
                                        version_job=self.version)
                )
                return render_template(self.template, **kwargs)

    def handle_form(self):
        # {'1': 'on',
        # '2': 'on',
        # 'checked_amount': '2',
        # 'folder': 'ScrapydWeb_demo',
        # 'project': 'demo',
        # 'version': '2018-09-05T03_13_50'}

        # With multinodes, would try to deploy to the first selected node first
        self.selected_nodes_amount = request.form.get('checked_amount', default=0, type=int)
        if self.selected_nodes_amount:
            self.selected_nodes = self.get_selected_nodes()
            self.first_selected_node = self.selected_nodes[0]
            self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVERS[self.first_selected_node - 1], 'addversion')
            # Note that self.first_selected_node != self.node
            self.AUTH = self.SCRAPYD_SERVERS_AUTHS[self.first_selected_node - 1]
        else:
            self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVER, 'addversion')

        # Error: Project names must begin with a letter and contain only letters, numbers and underscores
        self.project = re.sub(self.STRICT_NAME_PATTERN, '_', request.form.get('project', '')) or self.get_now_string()
        self.version = re.sub(self.LEGAL_NAME_PATTERN, '-', request.form.get('version', '')) or self.get_now_string()

        if request.files.get('file'):
            self.handle_uploaded_file()
        else:
            self.folder = request.form['folder']  # Used with SCRAPY_PROJECTS_DIR to get project_path
            self.handle_local_project()

    def handle_local_project(self):
        # Use folder instead of project
        project_path = os.path.join(self.SCRAPY_PROJECTS_DIR, self.folder)

        self.search_scrapy_cfg_path(project_path)
        if not self.scrapy_cfg_path:
            self.scrapy_cfg_not_found = True
            return

        self.eggname = '%s_%s.egg' % (self.project, self.version)
        self.eggpath = os.path.join(self.DEPLOY_PATH, self.eggname)
        self.build_egg()

    def handle_uploaded_file(self):
        # http://flask.pocoo.org/docs/1.0/api/#flask.Request.form
        # <class 'werkzeug.datastructures.FileStorage'>
        file = request.files['file']

        # Non-ASCII would be omitted and resulting the filename as to 'egg' or 'tar.gz'
        filename = secure_filename(file.filename)
        # tar.xz only works on Linux and macOS
        if filename in ['egg', 'zip', 'tar.gz']:
            filename = '%s_%s.%s' % (self.project, self.version, filename)
        else:
            filename = '%s_%s_from_file_%s' % (self.project, self.version, filename)

        if filename.endswith('egg'):
            self.eggname = filename
            self.eggpath = os.path.join(self.DEPLOY_PATH, self.eggname)
            file.save(self.eggpath)
            self.scrapy_cfg_not_found = False
        else:  # Compressed file
            filepath = os.path.join(self.DEPLOY_PATH, filename)
            file.save(filepath)
            tmpdir = self.uncompress_to_tmpdir(filepath)

            # Search from the root of tmpdir
            self.search_scrapy_cfg_path(tmpdir)
            if not self.scrapy_cfg_path:
                self.scrapy_cfg_not_found = True
                return

            self.eggname = re.sub(r'(\.zip|\.tar\.gz)$', '.egg', filename)
            self.eggpath = os.path.join(self.DEPLOY_PATH, self.eggname)
            self.build_egg()

    # https://gangmax.me/blog/2011/09/17/12-14-52-publish-532/
    # https://stackoverflow.com/a/49649784
    # When ScrapydWeb runs in Linux/macOS and tries to uncompress zip file from Windows_CN_cp936
    # UnicodeEncodeError: 'ascii' codec can't encode characters in position 7-8: ordinal not in range(128)
    # macOS + PY2 would raise OSError: Illegal byte sequence
    # Ubuntu + PY2 would raise UnicodeDecodeError in search_scrapy_cfg_path() though f.extractall(tmpdir) works well
    def uncompress_to_tmpdir(self, filepath):
        self.logger.debug("Uncompressing %s", filepath)
        tmpdir = tempfile.mkdtemp(prefix="scrapydweb-uncompress-")
        if zipfile.is_zipfile(filepath):
            with zipfile.ZipFile(filepath, 'r') as f:
                if PY2:
                    tmpdir = tempfile.mkdtemp(prefix="scrapydweb-uncompress-")
                    for filename in f.namelist():
                        try:
                            filename_utf8 = filename.decode('gbk').encode('utf8')
                        except (UnicodeDecodeError, UnicodeEncodeError):
                            filename_utf8 = filename
                        filepath_utf8 = os.path.join(tmpdir, filename_utf8)

                        try:
                            with io.open(filepath_utf8, 'wb') as f_utf8:
                                copyfileobj(f.open(filename), f_utf8)
                        except IOError:
                            # os.mkdir(filepath_utf8)
                            # zipfile from Windows "send to zipped" would meet the inner folder first:
                            # temp\\scrapydweb-uncompress-qrcyc0\\demo7/demo/'
                            mkdir_p(filepath_utf8)
                else:
                    # PY3: extractall() decodes a non-UTF-8 (e.g. Windows cp936)
                    # member name with cp437, producing mojibake folder names,
                    # and a member flagged UTF-8 but carrying invalid bytes could
                    # even abort the whole archive. Extract member by member and
                    # recover/normalize each name to a usable path instead.
                    for (member_name, err) in extract_zip_to_dir(f, tmpdir):
                        msg = "Skip illegal entry %s in %s: %s" % (
                            repr(member_name), os.path.basename(filepath), err)
                        self.logger.error(msg)
                        flash(msg, self.WARN)
        else:  # tar.gz
            with tarfile.open(filepath, 'r') as tar:  # Open for reading with transparent compression (recommended).
                tar.extractall(tmpdir)

        self.logger.debug("Uncompressed to %s", tmpdir)
        # In case uploading a compressed file in which scrapy_cfg_dir contains none ascii in python 2,
        # whereas selecting a project for auto packaging, scrapy_cfg_dir is unicode
        # print(repr(tmpdir))
        # print(type(tmpdir))
        return tmpdir.decode('utf8') if PY2 else tmpdir

    def search_scrapy_cfg_path(self, search_path, func_walk=os.walk, retry=True):
        try:
            scrapy_cfg_path, searched_paths = walk_for_scrapy_cfg(search_path, walk=func_walk)
        except UnicodeDecodeError:
            msg = "Found illegal filenames in %s" % search_path
            self.logger.error(msg)
            flash(msg, self.WARN)
            # In PY3, os.walk may also raise on undecodable on-disk names; retry
            # with safe_walk (which skips them) so that a valid scrapy.cfg residing
            # alongside the illegal names can still be located.
            if retry:
                self.search_scrapy_cfg_path(search_path, func_walk=self.safe_walk, retry=False)
            else:
                raise
        else:
            self.scrapy_cfg_searched_paths.extend(searched_paths)
            self.scrapy_cfg_path = scrapy_cfg_path
            if scrapy_cfg_path:
                self.logger.debug("scrapy_cfg_path: %s", scrapy_cfg_path)
            else:
                self.logger.error("scrapy.cfg not found in: %s", search_path)

    def build_egg(self):
        try:
            egg, tmpdir = _build_egg(self.scrapy_cfg_path)
        except ScrapyCfgParseError as err:
            self.logger.error(err)
            self.scrapy_cfg_parse_error = err
            return
        except CalledProcessError as err:
            self.logger.error(err)
            self.build_egg_subprocess_error = err
            return

        scrapy_cfg_dir = os.path.dirname(self.scrapy_cfg_path)
        copyfile(egg, os.path.join(scrapy_cfg_dir, self.eggname))
        copyfile(egg, self.eggpath)
        rmtree(tmpdir)
        self.logger.debug("Egg file saved to: %s", self.eggpath)

    def prepare_data(self):
        with io.open(self.eggpath, 'rb') as f:
            content = f.read()
            self.data = {
                'project': self.project,
                'version': self.version,
                'egg': content
            }

        self.slot.add_egg(self.eggname, content)


class DeployXhrView(BaseView):

    def __init__(self):
        super(DeployXhrView, self).__init__()

        self.eggname = self.view_args['eggname']
        self.project = self.view_args['project']
        self.version = self.view_args['version']

        self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVER, 'addversion')

        self.slot = slot

    def dispatch_request(self, **kwargs):
        content = self.slot.egg.get(self.eggname)
        # content = None  # For test only
        if not content:
            eggpath = os.path.join(self.DEPLOY_PATH, self.eggname)
            with io.open(eggpath, 'rb') as f:
                content = f.read()

        data = {
            'project': self.project,
            'version': self.version,
            'egg': content
        }
        status_code, js = self.make_request(self.url, data=data, auth=self.AUTH)
        return self.json_dumps(js, as_response=True)
