#!/usr/bin/env python

"""
A runnable script for managing a FireWorks database (a command-line interface to launchpad.py)
"""

from argparse import ArgumentParser
import os
import webbrowser
import time
import ast
import json
import datetime
import traceback

from pymongo import DESCENDING, ASCENDING
import yaml

from fireworks.fw_config import RESERVATION_EXPIRATION_SECS, \
    RUN_EXPIRATION_SECS, PW_CHECK_NUM, MAINTAIN_INTERVAL, CONFIG_FILE_DIR, \
    LAUNCHPAD_LOC
from fireworks.core.launchpad import LaunchPad
from fireworks.core.firework import Workflow, FireWork
from fireworks import __version__ as FW_VERSION
from fireworks import FW_INSTALL_DIR
from fireworks.user_objects.firetasks.script_task import ScriptTask
from fireworks.utilities.fw_serializers import DATETIME_HANDLER, recursive_dict
from fireworks.utilities.timing import any_fw_timers, print_fw_timers
from six.moves import input


__author__ = 'Anubhav Jain'
__credits__ = 'Shyue Ping Ong'
__copyright__ = 'Copyright 2013, The Materials Project'
__version__ = '0.1'
__maintainer__ = 'Anubhav Jain'
__email__ = 'ajain@lbl.gov'
__date__ = 'Feb 7, 2013'


DEFAULT_LPAD_YAML = "my_launchpad.yaml"


def pw_check(ids, args, skip_pw=False):
    if len(ids) > PW_CHECK_NUM and not skip_pw:
        m_password = datetime.datetime.now().strftime('%Y-%m-%d')
        if not args.password:
            if input('Are you sure? This will modify {} entries. (Y/N)'.format(len(ids)))[0].upper() == 'Y':
                args.password=datetime.datetime.now().strftime('%Y-%m-%d')
            else:
                raise ValueError('Operation aborted by user.')
        if args.password != m_password:
            raise ValueError("Modifying more than {} entries requires setting the --password parameter! (Today's date, e.g. 2012-02-25)".format(PW_CHECK_NUM))

    return ids


def parse_helper(lp, args, wf_mode=False, skip_pw=False):
    """
    Helper method to parse args that can take either id, name, state or query
    :param args:
    :return:
    """

    if args.fw_id and sum([bool(x) for x in [args.name, args.state, args.query]]) >= 1:
        raise ValueError('Cannot specify both fw_id and name/state/query)')

    query = {}
    if args.fw_id:
        return pw_check(args.fw_id, args, skip_pw)
    if args.query:
        query = ast.literal_eval(args.query)
    if args.name:
        query['name'] = args.name
    if args.state:
        query['state'] = args.state

    if wf_mode:
        return pw_check(lp.get_wf_ids(query), args, skip_pw)

    return pw_check(lp.get_fw_ids(query), args, skip_pw)


def get_lp(args):
    try:
        if not args.launchpad_file and os.path.exists(os.path.join(args.config_dir, DEFAULT_LPAD_YAML)):
            args.launchpad_file = os.path.join(args.config_dir, DEFAULT_LPAD_YAML)

        if args.launchpad_file:
            return LaunchPad.from_file(args.launchpad_file)
        else:
            args.loglvl = 'CRITICAL' if args.silencer else args.loglvl
            return LaunchPad(logdir=args.logdir, strm_lvl=args.loglvl)
    except:
        traceback.print_exc()
        err_message = 'FireWorks was not able to connect to MongoDB. Is the server running? The database file specified was {}.'.format(args.launchpad_file)
        if not args.launchpad_file:
            err_message += ' Type "lpad init" if you would like to set up a file that specifies location and credentials of your Mongo database (otherwise use default localhost configuration).'
        raise ValueError(err_message)


def init_yaml(args):
    fields = (
        ("host", "localhost"),
        ("port", 27017),
        ("name", "fireworks"),
        ("username", None),
        ("password", None))
    doc = {}
    print("Please supply the following configuration values")
    print("(press Enter if you want to accept the defaults)\n")
    for k, v in fields:
        val = input("Enter {} (default: {}) : ".format(k, v))
        doc[k] = val if val else v
    doc["port"] = int(doc["port"])  # enforce the port as an int
    with open(args.config_file, "w") as f:
        import yaml
        yaml.dump(LaunchPad.from_dict(doc).to_dict(), f)
        print("\nConfiguration written to {}!".format(args.config_file))


def reset(args):
    lp = get_lp(args)
    if not args.password:
        if input('Are you sure? This will RESET {} workflows and all data. (Y/N)'.format(lp.workflows.count()))[0].upper() == 'Y': args.password=datetime.datetime.now().strftime('%Y-%m-%d')
        else:
            raise ValueError('Operation aborted by user.')
    lp.reset(args.password)

def add_wf(args):
    lp = get_lp(args)
    if args.dir:
        files = []
        for f in args.wf_file:
            files.extend([os.path.join(f, i) for i in os.listdir(f)])
    else:
        files = args.wf_file
    for f in files:
        fwf = Workflow.from_file(f)
        lp.add_wf(fwf)

def add_wf_dir(args):
    lp = get_lp(args)
    for filename in os.listdir(args.wf_dir):
        fwf = Workflow.from_file(filename)
        lp.add_wf(fwf)

def get_fws(args):
    lp = get_lp(args)
    if sum([bool(x) for x in [args.fw_id, args.name, args.state, args.query]]) > 1:
        raise ValueError('Please specify exactly one of (fw_id, name, state, query)')
    if sum([bool(x) for x in [args.fw_id, args.name, args.state, args.query]]) == 0:
        args.query = '{}'
        args.display_format = args.display_format if args.display_format else 'ids'
    if sum([bool(x) for x in [args.fw_id, args.name, args.qid]]) > 1:
        raise ValueError('Please specify exactly one of (fw_id, name, qid)')
    else:
        args.display_format = args.display_format if args.display_format else 'more'

    if args.fw_id:
        query = {'fw_id': {"$in": args.fw_id}}
    elif args.name:
        query = {'name': args.name}
    elif args.state:
        query = {'state': args.state}
    elif args.query:
        query = ast.literal_eval(args.query)
    else:
        query = None

    if args.sort:
        sort = [(args.sort, ASCENDING)]
    elif args.rsort:
        sort = [(args.rsort, DESCENDING)]
    else:
        sort = None

    if args.qid:
        ids = lp.get_fw_ids_from_reservation_id(args.qid)
        if query:
            query['fw_id'] = {"$in": ids}
            ids = lp.get_fw_ids(query, sort, args.max)

    else:
        ids = lp.get_fw_ids(query, sort, args.max, count_only=args.display_format == 'count')
    fws = []
    if args.display_format == 'ids':
        fws = ids
    elif args.display_format == 'count':
        fws = [ids]
    else:
        for id in ids:
            fw = lp.get_fw_by_id(id)
            d = fw.to_dict()
            if args.display_format == 'more' or args.display_format == 'less':
                if 'archived_launches' in d:
                    del d['archived_launches']
                del d['spec']
            if args.display_format == 'less':
                if 'launches' in d:
                    del d['launches']
            fws.append(d)
    if len(fws) == 1:
        fws = fws[0]

    print(args.output(fws))


def get_wfs(args):
    lp = get_lp(args)
    if sum([bool(x) for x in [args.fw_id, args.name, args.state, args.query]]) > 1:
        raise ValueError('Please specify exactly one of (fw_id, name, state, query)')
    if sum([bool(x) for x in [args.fw_id, args.name, args.state, args.query]]) == 0:
        args.query = '{}'
        args.display_format = args.display_format if args.display_format else 'ids'
    else:
        args.display_format = args.display_format if args.display_format else 'more'

    if args.fw_id:
        query = {'nodes': {"$in": args.fw_id}}
    elif args.name:
        query = {'name': args.name}
    elif args.state:
        query = {'state': args.state}
    else:
        query = ast.literal_eval(args.query)

    if args.sort:
        sort = [(args.sort, ASCENDING)]
    elif args.rsort:
        sort = [(args.rsort, DESCENDING)]
    else:
        sort = None

    ids = lp.get_wf_ids(query, sort, args.max, count_only=args.display_format == 'count')
    if args.display_format == 'ids':
        wfs = ids
    elif args.display_format == 'count':
        wfs = [ids]
    else:
        wfs = []
        for i in ids:
            d = lp.get_wf_summary_dict(i, args.display_format)
            d["name"] += "--%d" % i
            wfs.append(d)

    if len(wfs) == 1:
        wfs = wfs[0]

    if args.table:
        headers = list(wfs[0].keys())
        from prettytable import PrettyTable
        t = PrettyTable(headers)
        for d in wfs:
            t.add_row([d.get(k) for k in headers])
        print(t)
    else:
        print(args.output(wfs))


def purge_wfs(args):
    lp = get_lp(args)
    if sum([bool(x) for x in [args.fw_id, args.name, args.state]]) > 1:
        raise ValueError('Please specify exactly one of (fw_id, name, state)')

    if args.fw_id:
        query = {'nodes': {"$in": args.fw_id}}
    elif args.name:
        query = {'name': args.name}
    elif args.state:
        query = {'state': args.state}
    else:
        raise ValueError('Please specify exactly one of (fw_id, name, state)')

    ids = lp.get_wf_ids(query)
    for i in ids:
        lp.purge_workflow(i)


def get_children(links, start, max_depth, data=[]):
    data = {}
    for l, c in links.items():
        if l == start:
            if len(c) > 0:
                data[l] = [get_children(links, i, max_depth) for i in c]
            else:
                data[l] = c
    return data

def get_links(args):
    lp = get_lp(args)

    query = {'nodes': {"$in": args.fw_id}}

    ids = lp.get_wf_ids(query, None, 0, count_only=False)
    for i in ids:
        d = lp.get_wf_summary_dict(i, "all")
        get_fwid = lambda l: int(l.split("--")[-1])
        links = {get_fwid(k): [get_fwid(i) for i in v]
                 for k, v in d["links"].items()}
        c = get_children(links, i, 3)

        import yaml
        print(yaml.dump(c))

def detect_lostruns(args):
    lp = get_lp(args)
    fl,ff = lp.detect_lostruns(expiration_secs=args.time, fizzle=args.fizzle, rerun=args.rerun, max_runtime=args.max_runtime)
    lp.m_logger.debug('Detected {} FIZZLED launches: {}'.format(len(fl), fl))
    lp.m_logger.info('Detected {} FIZZLED FWs: {}'.format(len(ff), ff))


def detect_unreserved(args):
    lp = get_lp(args)
    print(lp.detect_unreserved(expiration_secs=args.time, rerun=args.rerun))


def tuneup(args):
    lp = get_lp(args)
    lp.tuneup(bkground=not args.full)


def defuse(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args, wf_mode=True)
    for f in fw_ids:
        lp.defuse_wf(f)
        lp.m_logger.debug('Processed fw_id: {}'.format(f))
    lp.m_logger.info('Finished defusing {} FWs'.format(len(fw_ids)))


def archive(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args, wf_mode=True)
    for f in fw_ids:
        lp.archive_wf(f)
        lp.m_logger.debug('Processed fw_id: {}'.format(f))
    lp.m_logger.info('Finished archiving {} WFs'.format(len(fw_ids)))


def reignite(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args, wf_mode=True)
    for f in fw_ids:
        lp.reignite_wf(f)
        lp.m_logger.debug('Processed Workflow with fw_id: {}'.format(f))
    lp.m_logger.info('Finished reigniting {} Workflows'.format(len(fw_ids)))


def defuse_fws(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args)
    for f in fw_ids:
        lp.defuse_fw(f)
        lp.m_logger.debug('Processed fw_id: {}'.format(f))
    lp.m_logger.info('Finished defusing {} FWs'.format(len(fw_ids)))


def reignite_fws(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args)
    for f in fw_ids:
        lp.reignite_fw(f)
        lp.m_logger.debug('Processed fw_id: {}'.format(f))
    lp.m_logger.info('Finished reigniting {} FWs'.format(len(fw_ids)))


def rerun_fws(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args)
    for f in fw_ids:
        lp.rerun_fw(int(f))
        lp.m_logger.debug('Processed fw_id: {}'.format(f))
    lp.m_logger.info('Finished setting {} FWs to rerun'.format(len(fw_ids)))


def refresh(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args, wf_mode=True)
    for f in fw_ids:
        wf = lp.get_wf_by_fw_id(f)
        lp._refresh_wf(wf, f)
        lp.m_logger.debug('Processed Workflow with fw_id: {}'.format(f))
    lp.m_logger.info('Finished refreshing {} Workflows'.format(len(fw_ids)))

def get_qid(args):
    lp = get_lp(args)
    for f in args.fw_id:
        print(lp.get_reservation_id_from_fw_id(f))

def cancel_qid(args):
    lp = get_lp(args)
    lp.m_logger.warn("WARNING: cancel_qid does not actually remove jobs from the queue (e.g., execute qdel), this must be done manually!")
    lp.cancel_reservation_by_reservation_id(args.qid)

def set_priority(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args)
    for f in fw_ids:
        lp.set_priority(f, args.priority)
        lp.m_logger.debug("Processed fw_id {}".format(f))
    lp.m_logger.info("Finished setting priorities of {} FWs".format(len(fw_ids)))


def webgui(args):
    lp = get_lp(args)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fireworks.base_site.settings")
    os.environ["FWDB_CONFIG"] = json.dumps(lp.to_dict())
    from django.core.management import call_command
    from multiprocessing import Process
    p1 = Process(target=call_command,
                 args=("runserver",  "{}:{}".format(args.host, args.port)))
    p1.start()
    if not args.server_mode:
        time.sleep(2)
        webbrowser.open("http://{}:{}".format(args.host, args.port))
    p1.join()


def add_scripts(args):
    lp = get_lp(args)
    args.names = args.names if args.names else [None] * len(args.scripts)
    args.wf_name = args.wf_name if args.wf_name else args.names[0]
    fws = []
    links = {}
    for idx, s in enumerate(args.scripts):
        fws.append(FireWork(ScriptTask({'script': s, 'use_shell': True}), name=args.names[idx], fw_id=idx))
        if idx != 0:
            links[idx-1] = idx

    lp.add_wf(Workflow(fws, links, args.wf_name))


def recover_offline(args):
    lp = get_lp(args)
    failed_fws = []
    for l in lp.offline_runs.find({"completed": False, "deprecated": False}, {"launch_id": 1}):
        fw = lp.recover_offline(l['launch_id'], args.ignore_errors)
        if fw:
            failed_fws.append(fw)

    lp.m_logger.info("FINISHED recovering offline runs.")
    if failed_fws:
        lp.m_logger.info("FAILED to recover offline fw_ids: {}".format(failed_fws))


def forget_offline(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args)
    for f in fw_ids:
        lp.forget_offline(f)
        lp.m_logger.debug('Processed fw_id: {}'.format(f))

    lp.m_logger.info('Finished forget_offine, processed {} FWs'.format(len(fw_ids)))


def track_fws(args):
    lp = get_lp(args)
    fw_ids = parse_helper(lp, args, skip_pw=True)
    include = args.include
    exclude = args.exclude
    first_print = True  # used to control newline
    for f in fw_ids:
        data = lp.get_tracker_data(f)
        output = []
        for d in data:
            for t in d['trackers']:
                if (not include or t.filename in include) and (not exclude or t.filename not in exclude):
                    output.append('## Launch id: {}'.format(d['launch_id']))
                    output.append(str(t))

        if output:
            name = lp.fireworks.find_one({"fw_id": f}, {"name": 1})['name']
            output.insert(0, '# FW id: {}, FW name: {}'.format(f, name))
            if first_print:
                first_print = False
            else:
                output.insert(0, '>------<')
            print('\n'.join(output))


def version(args):
    print('FireWorks version:', FW_VERSION)
    print('located in:', FW_INSTALL_DIR)


def maintain(args):
    lp = get_lp(args)
    lp.maintain(args.infinite, args.maintain_interval)


def get_output_func(format):
    if format == "json":
        return lambda x: json.dumps(x, default=DATETIME_HANDLER,
                                    indent=4)
    else:
        return lambda x: yaml.dump(recursive_dict(x), default_flow_style=False)


def lpad():
    m_description = 'This script is used for creating and managing a FireWorks database (LaunchPad). For a list of ' \
                    'available commands, type "lpad -h". For more help on a specific command, ' \
                    'type "lpad <command> -h".'

    parser = ArgumentParser(description=m_description)

    parser.add_argument("-o", "--output", choices=["json", "yaml"],
                        default="json", type=str.lower,
                        help="Set output display format to either json or "
                             "YAML. YAML is easier to read for long "
                             "documents. JSON is the default.")

    subparsers = parser.add_subparsers(help='command', dest='command')

    init_parser = subparsers.add_parser(
        'init', help='Initialize a Fireworks launchpad YAML file.')
    init_parser.add_argument('--config-file', default=DEFAULT_LPAD_YAML,
                             type=str,
                             help="Filename to write to.")
    init_parser.set_defaults(func=init_yaml)

    reset_parser = subparsers.add_parser('reset', help='reset and re-initialize the FireWorks database')
    reset_parser.add_argument('--password', help="Today's date,  e.g. 2012-02-25. Password or positive response to input prompt required to protect against accidental reset.")
    reset_parser.set_defaults(func=reset)

    addwf_parser = subparsers.add_parser('add', help='insert a Workflow from file')
    addwf_parser.add_argument('-d', '--dir',
                              action="store_true",
                              help="Directory mode. Finds all files in the "
                                   "paths given by wf_file.")
    addwf_parser.add_argument('wf_file', nargs="+",
                              help="Path to a FireWork or Workflow file")
    addwf_parser.set_defaults(func=add_wf)

    # This makes common argument options easier to maintain. E.g., what if
    # there is a new state or disp option?
    fw_id_args = ["-i", "--fw_id"]
    fw_id_kwargs = {"type": int, "nargs": "+", "help": "fw_id"}

    state_args = ['-s', '--state']
    state_kwargs = {"type": str.upper, "help": "Select by state.",
                    "choices": FireWork.STATE_RANKS.keys()}
    disp_args = ['-d', '--display_format']
    disp_kwargs = {"type": str, "help": "Display format.", "default": "less",
                   "choices": ["all", "more", "less", "ids", "count"]}

    query_args = ["-q", "--query"]
    query_kwargs = {"help": 'Query (enclose pymongo-style dict in '
                            'single-quotes, e.g. \'{"state":"COMPLETED"}\')'}

    qid_args = ["--qid"]
    qid_kwargs = {"help": "Query by reservation id of job in queue"}

    get_fw_parser = subparsers.add_parser(
        'get_fws', help='get information about FireWorks')
    get_fw_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    get_fw_parser.add_argument('-n', '--name', help='get FWs with this name')
    get_fw_parser.add_argument(*state_args, **state_kwargs)
    get_fw_parser.add_argument(*query_args, **query_kwargs)
    get_fw_parser.add_argument(*qid_args, **qid_kwargs)
    get_fw_parser.add_argument(*disp_args, **disp_kwargs)
    get_fw_parser.add_argument('-m', '--max', help='limit results', default=0,
                               type=int)
    get_fw_parser.add_argument('--sort', help='Sort results',
                               choices=["created_on", "updated_on"])
    get_fw_parser.add_argument('--rsort', help='Reverse sort results',
                               choices=["created_on", "updated_on"])
    get_fw_parser.set_defaults(func=get_fws)

    get_wf_parser = subparsers.add_parser(
        'get_wfs', help='get information about Workflows')
    get_wf_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    get_wf_parser.add_argument('-n', '--name', help='get WFs with this name')
    get_wf_parser.add_argument(*state_args, **state_kwargs)
    get_wf_parser.add_argument(*query_args, **query_kwargs)
    get_wf_parser.add_argument(*disp_args, **disp_kwargs)
    get_wf_parser.add_argument('-m', '--max', help='limit results', default=0, type=int)
    get_wf_parser.add_argument('--sort', help='Sort results',
                               choices=["created_on", "updated_on"])
    get_wf_parser.add_argument('--rsort', help='Reverse sort results',
                               choices=["created_on", "updated_on"])
    get_wf_parser.add_argument('-t', '--table',
                               help='Print results in table form instead of '
                                    'json. Needs prettytable. Works best '
                                    'with "-d less"',
                               action="store_true")
    get_wf_parser.set_defaults(func=get_wfs)

    get_qid_parser = subparsers.add_parser('get_qids', help='get the queue id of a FireWork')
    get_qid_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    get_qid_parser.set_defaults(func=get_qid)

    cancel_qid_parser = subparsers.add_parser('cancel_qid', help='cancel a reservation')
    cancel_qid_parser.add_argument(*qid_args, **qid_kwargs)
    cancel_qid_parser.set_defaults(func=cancel_qid)

    get_links_parser = subparsers.add_parser(
            'get_links', help='Graphical display of Workflows')
    get_links_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    get_links_parser.add_argument(
        '-d', '--depth', help="Depth of links to search for.",
        default=1, type=int
    )

    get_links_parser.set_defaults(func=get_links)

    rerun_fws_parser = subparsers.add_parser('rerun_fws', help='re-run FireWork(s)')
    rerun_fws_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    rerun_fws_parser.add_argument('-n', '--name', help='name')
    rerun_fws_parser.add_argument(*state_args, **state_kwargs)
    rerun_fws_parser.add_argument(*query_args, **query_kwargs)
    rerun_fws_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    rerun_fws_parser.set_defaults(func=rerun_fws)

    reservation_parser = subparsers.add_parser('detect_unreserved', help='Find launches with stale reservations')
    reservation_parser.add_argument('--time', help='expiration time (seconds)',
                                    default=RESERVATION_EXPIRATION_SECS, type=int)
    reservation_parser.add_argument('--rerun', help='cancel and rerun expired reservations', action='store_true')
    reservation_parser.set_defaults(func=detect_unreserved)

    fizzled_parser = subparsers.add_parser('detect_lostruns',
                                           help='Find launches that have FIZZLED')
    fizzled_parser.add_argument('--time', help='expiration time (seconds)',
                                default=RUN_EXPIRATION_SECS,
                                type=int)
    fizzled_parser.add_argument('--fizzle', help='mark lost runs as fizzled', action='store_true')
    fizzled_parser.add_argument('--rerun', help='rerun lost runs', action='store_true')
    fizzled_parser.add_argument('--max_runtime', help='max runtime, helpful for tracing down walltime kills (seconds)',
                                type=int)
    fizzled_parser.set_defaults(func=detect_lostruns)

    defuse_parser = subparsers.add_parser('defuse', help='cancel (de-fuse) an entire Workflow')
    defuse_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    defuse_parser.add_argument('-n', '--name', help='name')
    defuse_parser.add_argument(*state_args, **state_kwargs)
    defuse_parser.add_argument(*query_args, **query_kwargs)
    defuse_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    defuse_parser.set_defaults(func=defuse)

    archive_parser = subparsers.add_parser('archive', help='archive an entire Workflow (irreversible)')
    archive_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    archive_parser.add_argument('-n', '--name', help='name')
    archive_parser.add_argument(*state_args, **state_kwargs)
    archive_parser.add_argument(*query_args, **query_kwargs)
    archive_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    archive_parser.set_defaults(func=archive)

    reignite_parser = subparsers.add_parser('reignite', help='reignite (un-cancel) an entire Workflow')
    reignite_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    reignite_parser.add_argument('-n', '--name', help='name')
    reignite_parser.add_argument(*state_args, **state_kwargs)
    reignite_parser.add_argument(*query_args, **query_kwargs)
    reignite_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    reignite_parser.set_defaults(func=reignite)

    defuse_fw_parser = subparsers.add_parser('defuse_fws', help='cancel (de-fuse) a single FireWork')
    defuse_fw_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    defuse_fw_parser.add_argument('-n', '--name', help='name')
    defuse_fw_parser.add_argument(*state_args, **state_kwargs)
    defuse_fw_parser.add_argument(*query_args, **query_kwargs)
    defuse_fw_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    defuse_fw_parser.set_defaults(func=defuse_fws)

    reignite_fw_parser = subparsers.add_parser('reignite_fws', help='reignite (un-cancel) a single FireWork')
    reignite_fw_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    reignite_fw_parser.add_argument('-n', '--name', help='name')
    reignite_fw_parser.add_argument(*state_args, **state_kwargs)
    reignite_fw_parser.add_argument(*query_args, **query_kwargs)
    reignite_fw_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    reignite_fw_parser.set_defaults(func=reignite_fws)

    maintain_parser = subparsers.add_parser('maintain', help='Run database maintenance')
    maintain_parser.add_argument('--infinite', help='loop infinitely', action='store_true')
    maintain_parser.add_argument('--maintain_interval', help='sleep time between maintenance loops (infinite mode)', default=MAINTAIN_INTERVAL, type=int)
    maintain_parser.set_defaults(func=maintain)

    tuneup_parser = subparsers.add_parser('tuneup',
                                          help='Tune-up the database (should be performed during scheduled downtime)')
    tuneup_parser.add_argument('--full', help='Run full tuneup and compaction (should be run during DB downtime only)', action='store_true')
    tuneup_parser.set_defaults(func=tuneup)

    refresh_parser = subparsers.add_parser('refresh', help='manually force a workflow refresh (not usually needed)')
    refresh_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    refresh_parser.add_argument('-n', '--name', help='name')
    refresh_parser.add_argument(*state_args, **state_kwargs)
    refresh_parser.add_argument(*query_args, **query_kwargs)
    refresh_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    refresh_parser.set_defaults(func=refresh)

    priority_parser = subparsers.add_parser('set_priority', help='modify the priority of one or more FireWorks')
    priority_parser.add_argument('priority', help='get FW with this fw_id', default=None, type=int)
    priority_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    priority_parser.add_argument('-n', '--name', help='name')
    priority_parser.add_argument(*state_args, **state_kwargs)
    priority_parser.add_argument(*query_args, **query_kwargs)
    priority_parser.add_argument('--password', help="Today's date, e.g. 2012-02-25. Password or positive response to input prompt required when modifying more than {} entries.".format(PW_CHECK_NUM))
    priority_parser.set_defaults(func=set_priority)

    version_parser = subparsers.add_parser(
        'version',
        help='Print the version and location of FireWorks installation')
    version_parser.set_defaults(func=version)

    parser.add_argument('-l', '--launchpad_file', help='path to LaunchPad file containing central DB connection info',
                        default=LAUNCHPAD_LOC)
    parser.add_argument('-c', '--config_dir',
                        help='path to a directory containing the LaunchPad file (used if -l unspecified)',
                        default=CONFIG_FILE_DIR)
    parser.add_argument('--logdir', help='path to a directory for logging')
    parser.add_argument('--loglvl', help='level to print log messages', default='INFO')
    parser.add_argument('-s', '--silencer', help='shortcut to mute log messages', action='store_true')

    webgui_parser = subparsers.add_parser('webgui', help='launch the web GUI')
    webgui_parser.add_argument("--port", dest="port", type=int, default=8000,
                        help="Port to run the server on (default: 8000)")

    webgui_parser.add_argument("--host", dest="host", type=str, default="127.0.0.1",
                        help="Host to run the server on (default: 127.0.0.1)")
    webgui_parser.add_argument('-s', '--server_mode', help='run in server mode (skip opening the browser)', action='store_true')
    webgui_parser.set_defaults(func=webgui)

    addscript_parser = subparsers.add_parser('add_scripts', help='quickly add a script (or several scripts) to run in sequence')
    addscript_parser.add_argument('scripts', help="Script to run, or space-separated names", nargs='*')
    addscript_parser.add_argument('-n', '--names', help='FireWork name, or space-separated names', nargs='*')
    addscript_parser.add_argument('-w', '--wf_name', help='Workflow name')
    addscript_parser.add_argument('-d', '--delimiter', help='delimiter for separating scripts', default=',')
    addscript_parser.set_defaults(func=add_scripts)

    recover_parser = subparsers.add_parser('recover_offline', help='recover offline workflows')
    recover_parser.add_argument('-i', '--ignore_errors', help='ignore errors', action='store_true')
    recover_parser.set_defaults(func=recover_offline)

    forget_parser = subparsers.add_parser('forget_offline', help='forget offline workflows')
    forget_parser.add_argument('-n', '--name', help='name')
    forget_parser.add_argument(*state_args, **state_kwargs)
    forget_parser.add_argument(*query_args, **query_kwargs)
    forget_parser.set_defaults(func=forget_offline)

    trackfw_parser = subparsers.add_parser('track_fws', help='Track FireWorks')
    trackfw_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    trackfw_parser.add_argument('-n', '--name', help='name')
    trackfw_parser.add_argument(*state_args, **state_kwargs)
    trackfw_parser.add_argument(*query_args, **query_kwargs)
    trackfw_parser.add_argument('-c', '--include', nargs="+",
                                help='only include these files in the report')
    trackfw_parser.add_argument('-x', '--exclude', nargs="+",
                                help='exclude these files from the report')
    trackfw_parser.set_defaults(func=track_fws)

    purge_wfs_parser = subparsers.add_parser(
        'purge_wfs', help='Purge workflows. WARNING: This does not handle duplicate-checked FireWorks well!')
    purge_wfs_parser.add_argument(*fw_id_args, **fw_id_kwargs)
    purge_wfs_parser.add_argument('-n', '--name', help='get FWs with this name')
    purge_wfs_parser.add_argument(*state_args, **state_kwargs)
    purge_wfs_parser.set_defaults(func=purge_wfs)

    args = parser.parse_args()

    args.output = get_output_func(args.output)

    args.func(args)

    if any_fw_timers():
        print_fw_timers()

if __name__ == '__main__':
    lpad()