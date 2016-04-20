#!/usr/bin/env python2
"""Run executable or ansible playbook on localhost

This takes care of fetching the script, unpacking it if it is a tarball or
zip file and actually executing the script. If the script is an ansible
playbook, then it bootstraps a python virtualenv where it installs ansible.

Only system wide requirement is a python2 interpreter >= 2.4.

"""

import os
import json
import sys
import glob
import copy
import random
import urllib
import logging
import tarfile
import zipfile
import tempfile
import subprocess
import json

import shutil


# these settings affect ansible playbooks
PYPI_URL = "https://pypi.python.org/packages/source"
VENV_VERSION = "1.11.6"
ANSIBLE_VERSION = "1.7.2"


log = logging.getLogger(__name__)


def shellcmd(cmd, env={}, su=False, break_on_error=True):
    """Run a command using the shell"""
    environ = os.environ.copy()
    environ.update(env)
    if su:
        log.debug("Running command in su mode.")
        p = subprocess.Popen(['sudo','-E' ,'su'], env=environ, stdin=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        print(p.communicate(cmd))
        return_code = p.returncode
    else:
        log.debug("Running command '%s'.", cmd)
        return_code = subprocess.call(cmd, env=environ, shell=True)
    if return_code:
        err = "Command '%s' exited with return code %d." % (cmd, return_code)
        if break_on_error:
            raise Exception(err)
        else:
            log.error(err)
    return return_code


def download(url, path=None):
    """Download a file over HTTP"""
    log.debug("Downloading %s.", url)
    name, headers = urllib.urlretrieve(url, path)
    log.debug("Downloaded to %s.", name)
    return name


def unpack(path, dirname='.'):
    """Unpack a tar or zip archive"""
    if tarfile.is_tarfile(path):
        log.debug("Unpacking '%s' tarball in directory '%s'.", path, dirname)
        tfile = tarfile.open(path)
        if hasattr(tfile, 'extractall'):
            tfile.extractall(dirname)
        else:
            for tarinfo in tfile:
                if tarinfo.isdir():
                    tarinfo = copy.copy(tarinfo)
                    tarinfo.mode = 0700
                tfile.extract(tarinfo, dirname)
    elif zipfile.is_zipfile(path):
        log.debug("Unpacking '%s' zip archive in directory '%s'.",
                  path, dirname)
        zfile = zipfile.ZipFile(path)
        if hasattr(zfile, 'extractall'):
            zfile.extractall(dirname)
        else:
            for member_path in zfile.namelist():
                dirname, filename = os.path.split(member_path)
                if dirname and not os.path.exists(dirname):
                    os.makedirs(dirname)
                zfile.extract(member_path, dirname)
    else:
        raise Exception("File '%s' is not a valid tar or zip archive." % path)




def bootstrap_template(blueprint, inputs):

    path = find_folder('scripts')
    os.chdir(path)
    f = open("inputs.yaml", "wb")
    f.write(inputs)
    f.close()
    if not os.path.isfile("/template_venv"):
        shellcmd("virtualenv /template_venv", break_on_error=False)
    shellcmd("/template_venv/bin/pip install cloudify", break_on_error=False)
    shellcmd("/template_venv/bin/pip install -r dev-requirements.txt")
    cmd = '/template_venv/bin/cfy local init -p {0} -i inputs.yaml'.format(blueprint)
    return shellcmd(cmd, break_on_error=False)


def run_template(workflow):
    cmd = "/template_venv/bin/cfy local execute -w {0}".format(workflow)
    return shellcmd(cmd, break_on_error=False)


def find_folder(dirname='.'):
    """Find absolute path of script"""
    dirname = os.path.abspath(dirname)
    if not os.path.isdir(dirname):
        log.warning("Directory '%s' doesn't exist, will search in '%s'.",
                    dirname, os.getcwd())
        dirname = os.getcwd()
    ldir = os.listdir(dirname)
    if not ldir:
        raise Exception("Directory '%s' is empty." % dirname)
    if len(ldir) == 1:
        path = os.path.join(dirname, ldir[0])
        if os.path.isdir(path):
            dirname = path
            return path
    else:
        raise Exception("No folder found")


def find_path(dirname='.', filename=''):
    """Find absolute path of script"""
    dirname = os.path.abspath(dirname)
    if not os.path.isdir(dirname):
        log.warning("Directory '%s' doesn't exist, will search in '%s'.",
                    dirname, os.getcwd())
        dirname = os.getcwd()
    while True:
        log.debug("Searching for entrypoint '%s' in directory '%s'.",
                  filename or 'main.*', dirname)
        ldir = os.listdir(dirname)
        if not ldir:
            raise Exception("Directory '%s' is empty." % dirname)
        if len(ldir) == 1:
            path = os.path.join(dirname, ldir[0])
            if os.path.isdir(path):
                dirname = path
                continue
            break
        if filename:
            path = os.path.join(dirname, filename)
            if os.path.isfile(path):
                break
        paths = glob.glob(os.path.join(dirname, 'main.*'))
        if not paths:
            raise Exception("No files match 'main.*' in '%s'." % dirname)
        if len(paths) > 1:
            log.warning("Multiple files match 'main.*' in '%s'.", dirname)
        path = paths[0]
        break
    log.info("Found entrypoint '%s'.", path)
    return path


def parse_args():
    """Parse command line arguments"""
    try:
        import argparse
        parser = argparse.ArgumentParser(
            description="Fetch and run executable script or ansible playbook.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument('script',
                            help="Url or path of script location.")
        parser.add_argument(
            '-f', '--file', type=str,
            help="If script is a tar or zip archive, optionally specify "
                 "relative path of script file inside archive.")
        parser.add_argument('-p', '--params', type=str,
                            help="String of params to pass to script.")
        parser.add_argument('-i', '--instance', type=str, default=[],
                            help="Instances to pass to script.")
        parser.add_argument('-d', '--workdata', type=str, default="",
                            help="params for workflow.")

        parser.add_argument('-w', '--workflow', type=str, default='install',
                            help="Run workflow on orchestration template.")
        parser.add_argument('-v', '--verbose', action='store_true',
                            help="Show debug logs.")
        args = parser.parse_args()
    except ImportError:
        # Python 2.6 does not have argparse
        import optparse
        parser = optparse.OptionParser("usage: %prog [options] script")
        parser.add_option(
            '-f', '--file', type=str,
            help="If script is a tar or zip archive, optionally specify "
                 "relative path of script file inside archive.")
        parser.add_option('-p', '--params', type=str,
                          help="String of params to pass to script.")
        parser.add_option('-i', '--instances', type=str,
                          help="String of params to pass to script.")
        parser.add_option('-d', '--workdata', type=str,
                          help="String of params to pass to workflow.")
        parser.add_option('-w', '--workflow', type=str,
                          help="Run workflow on orchestration template.")
        parser.add_option('-v', '--verbose', action='store_true',
                          help="Show debug logs.")
        args, list_args = parser.parse_args()
        args.script = list_args[0]
    return args


def main():
    """Fetch and run executable script or ansible playbook"""

    args = parse_args()

    loglvl = logging.DEBUG if args.verbose else logging.INFO
    logfmt = "[%(asctime)-15s][%(levelname)s] - %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(logfmt))
    handler.setLevel(loglvl)  # Overridden by configuration
    log.addHandler(handler)
    log.setLevel(loglvl)


    randid = '%x' % random.randrange(2 ** 128)
    mksep = lambda part: '-----part-%s-%s-----' % (part, randid)
    kwargs = {}
    print mksep('bootstrap')
    try:
        if os.path.isfile(args.script):
            path = args.script
        else:
            path = download(args.script)
        try:
            unpack(path, '/tmp/templates/')
        except:
            pass
        else:
            path = find_path('/tmp/templates', args.file)

        inputs = ""
        if args.params:
            inputs = args.params
        folder = find_folder('/tmp/templates')
        os.chdir(folder)
        log.debug("Directory '%s' " % os.listdir("."))

        f = open("inputs.json", "wb")
        f.write(inputs)
        f.close()

        if not os.path.isfile("/template_venv"):
            shellcmd("virtualenv /template_venv", break_on_error=False)
        shellcmd("/template_venv/bin/pip install cloudify", break_on_error=False)
        shellcmd("/template_venv/bin/pip install https://github.com/mistio/mist.client/archive/cloudify_integration.zip", break_on_error=False)
        shellcmd("git clone https://github.com/mistio/cloudify-mist-plugin /template_venv/mist_plugin", break_on_error=False)
        os.chdir("/template_venv/mist_plugin/")
        shellcmd("/template_venv/bin/python setup.py develop")
        os.chdir(folder)
        shellcmd("/template_venv/bin/pip install -r dev-requirements.txt")
        cmd = '/template_venv/bin/cfy local init -p {0} -i inputs.json'.format(path)
        local_instances = os.path.join(folder,
                                       "local-storage/local/node-instances")
        shellcmd(cmd, break_on_error=False)
        if args.instance:
            log.debug("Instances exist" + args.instance)
            shutil.rmtree('local-storage/local/node-instances')
            os.mkdir("local-storage/local/node-instances")
            instances = json.loads(args.instance)
            for instance in instances:
                data = open(os.path.join(local_instances, instance["id"]),"w")
                data.write(json.dumps(instance))
                data.close()
        print mksep('end')
        print mksep('execute')
        cmd = "/template_venv/bin/cfy local execute -w {0}".format(args.workflow)
        try:
            data = json.loads(args.workdata)
            print data
            if data.keys():
                f = open("workflow_inputs.json", "wb")
                f.write(args.workdata)
                f.close()
                cmd = cmd + " -p workflow_inputs.json"
        except Exception:
            pass
        exit_code = shellcmd(cmd, break_on_error=False)
        # cloudify_data = find_path("local-storage/local", "data")
        # cloudify_data = open(cloudify_data).read()
        # cloudify_instances = {}
        for instance in os.listdir(local_instances):
            print mksep('end')
            print mksep('cloudifyinstance')
            print open(os.path.join(local_instances, instance)).read()

        # out_paths = ('output', os.path.join(os.path.dirname(path), 'output'))
        # for out_path in out_paths:
        #     if os.path.isfile(out_path):
        #         print mksep('end')
        #         print mksep('outfile')
        #         try:
        #             with open(out_path) as fobj:
        #                 print fobj.read()
        #         except Exception as exc:
        #             log.error("Error reading '%s' file: %r", out_path, exc)
        #         break
        print mksep('end')
        print mksep('end')
        print mksep('summary')
        log.info("Wrapper script execution completed successfully. "
                 "User script exited with rc %s." % exit_code)
        print mksep('end')
        return exit_code
    except Exception as exc:
        print mksep('end')
        print mksep('summary')
        log.critical(exc)
        print mksep('end')
        return -1


if __name__ == "__main__":
    sys.exit(main())
