"""Command-line interface for uploading data."""

from __future__ import unicode_literals, print_function

import os
import os.path as osp
from argparse import ArgumentParser
from configparser import ConfigParser
from collections import OrderedDict
from getpass import getuser

from prompt_toolkit import prompt as ptkprompt
from prompt_toolkit.token import Token
from prompt_toolkit.contrib.completers import WordCompleter

from .core import crawl_data_dir, get_sessions, check_internet_connection
from .upload import Uploader

SUBCOMMANDS = ("host", "imaging", "clinical", "experiment")

_toolbar_texts = {
    'default': 'Press tab to see options',
    'subject': 'Invalid subject',
    'experiment': 'Invalid experiment',
    'session': 'Invalid session'
}


def make_parser():
    """Define command-line arguments."""
    parser = ArgumentParser(description="Upload RAM data", prog="ramup")
    parser.add_argument('--experiment', '-x', type=str, help="Experiment type")
    parser.add_argument('--session', '-n', type=int, help="Session number")
    parser.add_argument('--dataroot', '-r', type=str, help="Root data directory")
    parser.add_argument('--local-upload', '-l', action='store_true', default=False,
                        help='"Upload" files locally (for testing)')
    parser.add_argument('--ssh-key', '-k', type=str,
                        help="SSH keys to use when uploading")
    parser.add_argument('subcommand', type=str, choices=SUBCOMMANDS, nargs='?',
                        help="Action to run")
    return parser


def make_toolbar(text):
    def toolbar(cli):
        return [(Token.Toolbar, text)]
    return toolbar


def prompt(msg, toolbar_msg_key='default', **kwargs):
    toolbar = make_toolbar(_toolbar_texts[toolbar_msg_key])
    return ptkprompt(msg, get_bottom_toolbar_tokens=toolbar, **kwargs)


def prompt_subcommand():
    """Prompt for the subcommand to run if not given on the command-line."""
    mapped = OrderedDict([
        ("clinical", "Upload clinical EEG data"),
        ("imaging", "Upload imaging data"),
        ("host", "Transfer EEG data from the host PC"),
        ("experiment", "Upload all experimental data")
    ])
    completer = WordCompleter([value for _, value in mapped.items()])
    cmd = ''
    while cmd not in SUBCOMMANDS:
        res = prompt("Action: ", completer=completer)
        for key in mapped:
            if res == mapped[key]:
                cmd = key
    return cmd


def prompt_subject(subjects, allow_any=False):
    """Prompt for the subject to upload data for."""
    completer = WordCompleter(subjects)
    subject = ''
    key = 'default'
    while subject not in subjects:
        subject = prompt("Subject: ", toolbar_msg_key=key, completer=completer)
        if allow_any:
            # For uploading arbitrary stuff for testing, we don't really care if
            # the subject isn't real.
            break
        key = 'subject'
    return subject


def prompt_experiment(experiments):
    """Prompt for the experiment type to upload."""
    completer = WordCompleter(experiments)
    exp = ''
    key = 'default'
    while exp not in experiments:
        exp = prompt("Experiment: ", toolbar_msg_key=key, completer=completer)
        key = 'experiment'
    return exp


def prompt_session(sessions, allow_any=False):
    """Prompt for the session number to upload."""
    completer = WordCompleter(['{}'.format(session) for session in sessions])
    session = -1
    key = 'session'
    while session not in sessions:
        try:
            session = int(prompt("Session: ", toolbar_msg_key=key,
                                 completer=completer))
        except TypeError:
            continue
        else:
            if allow_any:
                break
            key = 'session'
    return session


def prompt_directory(initialdir=os.getcwd()):
    """Open a file dialog to select a directory.

    :param str initialdir: Directory to start looking in.
    :returns: Selected path.

    """
    try:
        from tkinter import Tk
        from tkinter.filedialog import askdirectory
    except ImportError:
        from Tkinter import Tk
        from tkFileDialog import askdirectory
    root = Tk()
    root.withdraw()
    path = askdirectory(initialdir=initialdir, title="Select directory")
    del root
    if not len(path):
        raise RuntimeError("Cancelled!")
    return path


def main():
    # Read config file for default settings
    config = ConfigParser()
    config.read(osp.join(osp.dirname(__file__), 'config.ini'))
    host_pc = dict(config['host_pc'])  # Host PC settings
    transferred = dict(config['transferred'])  # Uploaded data settings

    parser = make_parser()
    parser.add_argument('--subject', '-s', type=str, help="Subject ID")
    args = parser.parse_args()

    available = crawl_data_dir(path=args.dataroot)

    # Fail if there is no Internet connection.
    check_internet_connection()

    try:
        # Remote server URL
        url = '{user:s}@{hostname:s}:{remote_dir:s}'
        remote = {'user': getuser()}
        remote.update(dict(config['ramtransfer']))
        remote['key'] = remote['key'].format(user=remote['user'])

        # Get common options
        subcommand = args.subcommand or prompt_subcommand()
        allow_any_subject = True  # subcommand != 'experiment'
        subject = args.subject or prompt_subject(sorted(list(available.keys())),
                                                 allow_any=allow_any_subject)

        # Create uploader
        uploader = Uploader(subject, host_pc, transferred, remote,
                            dataroot=args.dataroot)

        # Perform primary actions
        if subcommand in ['host', 'experiment']:
            # Allow transferring data for AmplitudeDetermination experiments
            if 'AmplitudeDetermination' not in available[subject]:
                available[subject].append('AmplitudeDetermination')
            experiment = args.experiment or prompt_experiment(available[subject])

            if args.session is None:
                allow_any_session = experiment == 'AmplitudeDetermination'
                session = prompt_session(get_sessions(subject, experiment, path=args.dataroot),
                                         allow_any=allow_any_session)
            else:
                session = args.session

            if subcommand == 'experiment':
                print("Beginning experiment data upload...")
                if args.local_upload:
                    print("Select destination directory")
                    dest = prompt_directory(osp.expanduser("~"))
                else:
                    dest = None  # FIXME
                uploader.upload_experiment_data(experiment, session, dest)
            elif subcommand == 'host':
                # This shouldn't need to be called separately since the upload task
                # calls it automatically, but it may be useful to do this ahead of
                # time.
                print("Beginning host data transfer...")
                uploader.transfer_host_data(experiment, session)
        else:
            remote['remote_dir'] = config.get(subcommand, 'remote_dir')

            def _dest_dir():
                if args.local_upload:
                    print("Select destination directory")
                    dest = prompt_directory(osp.expanduser("~"))
                else:
                    dest = url.format(**remote)
                return dest

            if subcommand == 'imaging':
                print("Select imaging directory to upload")
                src = prompt_directory()
                uploader.upload_imaging(src, _dest_dir())
            elif subcommand == 'clinical':
                print("Select clinical EEG data directory to upload")
                src = prompt_directory()
                uploader.upload_clinical_eeg(src, _dest_dir())
    except KeyboardInterrupt:
        print("Aborting!")
