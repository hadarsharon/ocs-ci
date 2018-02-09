import logging

import yaml

from ceph.utils import setup_deb_repos
from ceph.utils import setup_repos, check_ceph_healthly

log = logging.getLogger(__name__)


def run(**kw):
    log.info("Running test")
    ceph_nodes = kw.get('ceph_nodes')
    log.info("Running ceph ansible test")
    config = kw.get('config')
    test_data = kw.get('test_data')
    build = test_data['ceph-ansible']['rhbuild']

    ubuntu_repo = None
    ceph_installer = None
    ceph_mon = None
    base_url = None

    if config.get('ubuntu_repo'):
        ubuntu_repo = config.get('ubuntu_repo')
    if config.get('base_url'):
        base_url = config.get('base_url')
    installer_url = None
    if config.get('installer_url'):
        installer_url = config.get('installer_url')
    if config.get('skip_setup') is True:
        log.info("Skipping setup of ceph cluster")
        return 0
    for node in ceph_nodes:
        if node.role == 'installer':
            ceph_installer = node
        elif node.role == 'mon':
            ceph_mon = node

    for ceph in ceph_nodes:
        # setup latest repo's
        if ceph.pkg_type == 'deb':
            setup_deb_repos(ceph, ubuntu_repo)
        else:
            setup_repos(ceph, base_url, installer_url)
            log.info("Using the cdn repo for the test")
        log.info("Updating metadata")
        if ceph.pkg_type == 'rpm':
            ceph.exec_command(sudo=True, cmd='yum update metadata')

    ceph_installer.exec_command(
        sudo=True, cmd='cd cd; yum install -y ceph-ansible ; sleep 4')
    ceph_installer.exec_command(
        cmd='cp -R /usr/share/ceph-ansible ~/ ; sleep 2')

    # If upgrading from version 2 update all.yml and hosts file
    if build.startswith('2'):
        log.info("Upgrading from version 2")
        gvar = yaml.dump(config.get('ansi_config'), default_flow_style=False)
        log.info("global vars " + gvar)
        gvars_file = ceph_installer.write_file(
            file_name='ceph-ansible/group_vars/all.yml', file_mode='w')
        gvars_file.write(gvar)
        gvars_file.flush()

        log.info("Adding mons as mgrs in hosts file")
        mon_nodes = [node for node in ceph_nodes if node.role == 'mon']
        mgr_block = '[mgrs]\n'
        for node in mon_nodes:
            mgr_block += node.shortname + ' monitor_interface=' + node.eth_interface + '\n'

        host_file = ceph_installer.write_file(file_name='ceph-ansible/hosts', file_mode='a')
        host_file.write(mgr_block)
        host_file.flush()

        log.info(mgr_block)

    # copy rolling update from infrastructure playbook
    ceph_installer.exec_command(cmd='cd ceph-ansible ; cp infrastructure-playbooks/rolling_update.yml .')
    out, rc = ceph_installer.exec_command(
        cmd='cd ceph-ansible ; ansible-playbook -e ireallymeanit=yes -vv -i hosts rolling_update.yml',
        long_running=True)

    # check if all mon's and osd's are in correct state
    num_osds = test_data['ceph-ansible']['num-osds']
    num_mons = test_data['ceph-ansible']['num-osds']
    if rc != 0:
        log.info("Failed during upgrade")
        return rc
    return check_ceph_healthly(ceph_mon, num_osds, num_mons)