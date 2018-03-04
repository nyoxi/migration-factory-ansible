#!/usr/bin/python2

#
# Copyright (c) 2018 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from contextlib import contextmanager
import json
import logging
import os
import re
import sys
import tempfile
import time

import six

if six.PY2:
    import subprocess32 as subprocess
else:
    import subprocess

# import ovirtsdk4 as sdk
# import ovirtsdk4.types as types

LOG_LEVEL = logging.DEBUG
STATE_DIR = '/tmp'
VDSM_LOG_DIR = '/var/log/vdsm/import'
VDSM_UID = 36

# Tweaks
VDSM = False
DIRECT_BACKEND = not VDSM


def error(msg):
    logging.error(msg)
    sys.stderr.write(msg)
    sys.exit(1)


def make_vdsm():
    """Makes sure the process runs as vdsm user"""
    uid = os.geteuid()
    if uid == VDSM_UID:
        logging.debug('Already running as vdsm user')
        return
    elif uid == 0:
        logging.debug('Restarting as vdsm user')
        os.chdir('/')
        cmd = '/usr/bin/sudo'
        args = [cmd, '-u', 'vdsm']
        args.extend(sys.argv)
        os.execv(cmd, args)
    sys.stderr.write('Need to run as vdsm user or root!\n')
    sys.exit(1)


def daemonize():
    """Properly deamonizes the process and closes file desriptors."""
    sys.stderr.flush()
    sys.stdout.flush()

    pid = os.fork()
    if pid != 0:
        # Nothing more to do for the parent
        sys.exit(0)

    os.setsid()
    pid = os.fork()
    if pid != 0:
        # Nothing more to do for the parent
        sys.exit(0)

    os.umask(0)
    os.chdir('/')

    dev_null = open('/dev/null', 'w')
    os.dup2(dev_null.fileno(), sys.stdin.fileno())
    os.dup2(dev_null.fileno(), sys.stdout.fileno())
    os.dup2(dev_null.fileno(), sys.stderr.fileno())


class OutputParser(object):

    COPY_DISK_RE = re.compile(br'.*Copying disk (\d+)/(\d+) to.*')
    DISK_PROGRESS_RE = re.compile(br'\s+\((\d+\.\d+)/100%\)')

    def __init__(self, v2v_log):
        self._log = open(v2v_log, 'rU')

    def parse(self, state):
        line = None
        while line != '':
            line = self._log.readline()
            m = self.COPY_DISK_RE.match(line)
            if m is not None:
                try:
                    state['current_disk'] = int(m.group(1))
                    state['disk_count'] = int(m.group(2))
                    logging.info('Copying disk %d/%d',
                                 state['current_disk'], state['disk_count'])
                except ValueError:
                    logging.exception('Conversion error')
            m = self.DISK_PROGRESS_RE.match(line)
            if m is not None:
                state['progress'] = m.group(1)
                logging.info('Updated progress: %s', state['progress'])
        return state

    def close(self):
        self._log.close()


@contextmanager
def log_parser(v2v_log):
    parser = None
    try:
        parser = OutputParser(v2v_log)
        yield parser
    finally:
        if parser is not None:
            parser.close()


def write_state(state):
    with open(state_file, 'w') as f:
        json.dump(state, f)


def wrapper(data, state_file, v2v_log):
    v2v_args = [
        '/usr/bin/virt-v2v', '-v', '-x',
        data['vm_name'],
        '-ic', data['vmware_uri'],
        '--password-file', data['vmware_password_file'],
    ]

    if data['transport_method'] == 'vddk':
        v2v_args.extend([
            '-it', 'vddk',
            '--vddk-libdir', '/opt/vmware-vix-disklib-distrib',
            '--vddk-thumbprint', data['vmware_fingerprint'],
            ])

    if 'export_domain' in data:
        v2v_args.extend([
            '-o', 'rhv',
            '-os', data['export_domain'],
            ])

    proc = None
    with open(v2v_log, 'w') as log:
        env = os.environ.copy()
        env['LANG'] = 'C'
        if DIRECT_BACKEND:
            logging.debug('Using direct backend. Hack, hack...')
            env['LIBGUESTFS_BACKEND'] = 'direct'

        logging.info('Starting virt-v2v as: %r', v2v_args)
        proc = subprocess.Popen(
                v2v_args,
                stderr=subprocess.STDOUT,
                stdout=log,
                env=env,
                )

    try:
        state = {
            'started': True,
            'pid': proc.pid,
            'progress': 'initializing',
            }
        write_state(state)
        with log_parser(v2v_log) as parser:
            while proc.poll() is None:
                state = parser.parse(state)
                write_state(state)
                time.sleep(5)
            logging.info('virt-v2v terminated with return code %d',
                         proc.returncode)
            state = parser.parse(state)
    except Exception:
        logging.exception('Error while monitoring virt-v2v')
        logging.info('Killing virt-v2v process')
        proc.kill()

    state['return_code'] = proc.returncode
    state['finished'] = True
    write_state(state)

    # TODO
    # - post process OVF?
    # - clean disks on error?


###########

if VDSM:
    make_vdsm()

log_tag = '%s-%d' % (time.strftime('%Y%m%dT%H%M%S'), os.getpid())
v2v_log = os.path.join(VDSM_LOG_DIR, 'v2v-import-%s.log' % log_tag)
wrapper_log = os.path.join(VDSM_LOG_DIR, 'v2v-import-%s-wrapper.log' % log_tag)
state_file = os.path.join(STATE_DIR, 'v2v-import-%s.state' % log_tag)

logging.basicConfig(
    level=LOG_LEVEL,
    filename=wrapper_log,
    format='%(asctime)s:%(levelname)s: %(message)s (%(module)s:%(lineno)d)')

logging.info('Will store virt-v2v log in: %s', v2v_log)
logging.info('Will store state file in: %s', state_file)

password_files = []

try:
    logging.info('Processing input data')
    data = json.load(sys.stdin)

    # Make sure all the needed keys are in data. This is rather poor
    # validation, but...
    for k in [
            'vm_name',
            'vmware_fingerprint',
            'vmware_uri',
            'vmware_password',
            ]:
        if k not in data:
            error('Missing argument: %s' % k)

    # Transports (only VDDK for now)
    if 'transport_method' not in data:
        error('No transport method specified')
    if data['transport_method'] != 'vddk':
        error('Unknown transport method: %s', data['transport_method'])

    # Targets (only export domain for now)
    if 'export_domain' not in data:
        error('No target specified')

    # Send some useful info on stdout in JSON
    print(json.dumps({
        'v2v_log': v2v_log,
        'wrapper_log': wrapper_log,
        'state_file': state_file,
    }))

    # Store password(s)
    logging.info('Writing password file(s)')

    pfile = tempfile.mkstemp(suffix='.v2v')
    data['vmware_password_file'] = pfile[1]
    password_files.append(data['vmware_password_file'])
    os.write(pfile[0], data['vmware_password'])
    os.close(pfile[0])

    # Let's get to work
    logging.info('Daemonizing')
    daemonize()
    wrapper(data, state_file, v2v_log)

    # Remove password files
    logging.info('Removing password files')
    for f in password_files:
        try:
            os.remove(f)
        except OSError:
            logging.exception('Error while removing password file: %s' % f)

except Exception:
    logging.exception('Wrapper failure')
    # Remove password files
    logging.info('Removing password files')
    for f in password_files:
        try:
            os.remove(f)
        except OSError:
            logging.exception('Error removing password file: %s' % f)
    # Re-raise original error
    raise

logging.info('Finished')
