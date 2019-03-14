from __future__ import print_function
import sys

import hashlib
import json
import pprint
import shutil
import threading

import paramiko

import itertools
# from numpy import random
from collections import OrderedDict

from subprocess import TimeoutExpired

from scp import SCPClient

from config.config import Configuration
from resource_assignment.network_plotter import NetworkPlotter
from resource_assignment.resource_assignment_problem import ResourceAllocationProblem

from scripts import purge_rabbit
from tests.utils.graph import Graph


def remote_sdo_worker(_host, _sdo_name, _services, _log_level, _conf_file):

    ssh_clients[_sdo_name] = paramiko.SSHClient()

    _ssh = ssh_clients[_sdo_name]
    _ssh.load_system_host_keys()
    _ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    _ssh.connect(remote_hosts[_host], username="gabriele")

    _stdin, _stdout, _stderr = _ssh.exec_command("cd dragon" + "; "
                                                 "python3 main.py {} {} -l {} -d {} -o".format(_sdo_name,
                                                                                               " ".join(_services),
                                                                                               _log_level,
                                                                                               _conf_file),
                                                 get_pty=True)
    _exit_status = stdout.channel.recv_exit_status()
    _ssh.close()

    for line in _stdout:
        print(line)
    for line in _stderr:
        print(line, file=sys.stderr)


remote_hosts = {
    "local": "127.0.0.1"
    # "node0": "10.0.0.1"
    # , "node1": "10.0.0.2"
}
remote_username = "gabriele"
remote_dragon_path = "dragon"

# init ssh clients
ssh_clients = dict()

p_list = list()

# [ Configuration ]
CONF_FILE = 'default-config.ini'
configuration = Configuration(CONF_FILE)
print("SDO_NUMBER:           " + str(configuration.SDO_NUMBER))
print("NEIGHBOR_PROBABILITY: " + str(configuration.NEIGHBOR_PROBABILITY))
print("NODE_NUMBER:          " + str(configuration.NODE_NUMBER))
print("BUNDLE_PERCENTAGE:    " + str(configuration.BUNDLE_PERCENTAGE))

# [ RAP instance ]
rap = ResourceAllocationProblem()
with open(configuration.RAP_INSTANCE, mode="r") as rap_file:
    rap.parse_dict(json.loads(rap_file.read()))
sdos = ["sdo"+str(n) for n in range(configuration.SDO_NUMBER)]
nodes = ["node" + str(n) for n in range(configuration.NODE_NUMBER)]

rap.sdos = sdos
rap.nodes = nodes
with open(configuration.RAP_INSTANCE, mode="w") as rap_file:
    rap_file.write(json.dumps(rap.to_dict(), indent=4))

# prepare remote hosts
print("preparing remote hosts")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.load_system_host_keys()

for host, address in remote_hosts.items():
    ssh.connect(address, username=remote_username)
    # purge rabbitmq queues
    stdin, stdout, stderr = ssh.exec_command('cd {}'.format(remote_dragon_path) + '; ' +
                                             'python3 -m scripts.purge_rabbit', get_pty=True)

    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {}".format(stdin, stdout, stderr, exit_status))

    # copy configuration and instance
    scp = SCPClient(ssh.get_transport())
    scp.put(["config/" + CONF_FILE, "config/" + configuration.RAP_INSTANCE],
            remote_dragon_path + "/config/")
    scp.close()

    # clean result directories
    stdin, stdout, stderr = ssh.exec_command('cd {}'.format(remote_dragon_path) + '; ' +
                                             'rm -r {}'.format(configuration.RESULTS_FOLDER), get_pty=True)
    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {}".format(stdin, stdout, stderr, exit_status))
    ssh.close()

# clean result directory
shutil.rmtree(configuration.RESULTS_FOLDER, ignore_errors=True)

# plot the topology
# NetworkPlotter(rap.sdos).graphical_plot()
NetworkPlotter(rap.sdos).print_topology()

# print total resources
total_resources = rap.get_total_resources_amount()
average_resource_per_function = {r: sum([rap.get_function_resource_consumption(f)[r] for f in rap.functions])/len(rap.functions) for r in rap.resources}
average_resource_percentage_per_function = sum([average_resource_per_function[r]/total_resources[r] for r in rap.resources])/len(rap.resources)
statistical_bundle_len = len(rap.services)*(configuration.BUNDLE_PERCENTAGE/100)
average_resource_demand = statistical_bundle_len*average_resource_percentage_per_function
print("- Resources Statistics - ")
print("Total resources: \n" + pprint.pformat(total_resources))
print("Average resources per function: \n" + pprint.pformat(average_resource_per_function))
print("Average demand percentage per function: " + str(round(average_resource_percentage_per_function, 3)))
print("Statistical bundle len: " + str(round(statistical_bundle_len, 2)))
print("Statistical average demand percentage per bundle: " + str(round(average_resource_demand, 3)))
print("Statistical total demand percentage: " + str(round(average_resource_demand*configuration.SDO_NUMBER, 3)))
print("- -------------------- - ")

# distribute sdos among physical nodes
graph = Graph(json.loads(configuration.TOPOLOGY_FILE), len(rap.sdos))
sdo_distribution = graph.compute_clusters(min(len(rap.sdos), len(remote_hosts)))

print("- Run Orchestration - ")
for i in range(configuration.SDO_NUMBER):
    sdo_name = "sdo" + str(i)
    service_bundle = [s for s in rap.services
                      if int(str(int(hashlib.sha256((sdo_name+s).encode()).hexdigest(), 16))[-2:]) < configuration.BUNDLE_PERCENTAGE]
    if len(service_bundle) == 0:
        service_bundle.append(rap.services[0])
    print(sdo_name + " : " + str(service_bundle))

    # run sdo instance on a physical node
    host = "node" + str(sdo_distribution[sdo_name])
    print("running instance " + sdo_name + " on host " + host)

    t = threading.Thread(target=remote_sdo_worker, args=(host,
                                                         sdo_name,
                                                         service_bundle,
                                                         configuration.LOG_LEVEL,
                                                         CONF_FILE))
    t.start()

    p_list.append(t)

killed = list()
for i, t in enumerate(p_list):
    try:
        t.join(timeout=50)
    except TimeoutExpired:
        ssh_clients['sdo' + str(i)].get_transport().close()
        ssh_clients['sdo' + str(i)].close()
        killed.append('sdo' + str(i))

print(" - Collect Results - ")

# fetch remote result files
for host, address in remote_hosts:
    ssh.connect(address, username=remote_username)

    stdin, stdout, stderr = ssh.exec_command("ls " + remote_dragon_path + "/*.log")
    log_files = stdout.read().split()

    scp = SCPClient(ssh.get_transport())
    # results
    scp.get(remote_dragon_path + "/" + configuration.RESULTS_FOLDER + "/", recursive=True)
    # logs
    for log_file in log_files:
        scp.get(remote_dragon_path + "/" + log_file)
    scp.close()
    ssh.close()

# fetch post process information
placements = dict()
message_rates = dict()
private_utilities = list()
for i in range(configuration.SDO_NUMBER):
    sdo_name = "sdo" + str(i)
    utility_file = configuration.RESULTS_FOLDER + "/utility_" + sdo_name + ".json"
    placement_file = configuration.RESULTS_FOLDER + "/placement_" + sdo_name + ".json"
    rates_file = configuration.RESULTS_FOLDER + "/rates_" + sdo_name + ".json"

    if sdo_name in killed:
        private_utilities.append(0)
        placements[sdo_name] = []
        message_rates[sdo_name] = OrderedDict([("0:0", 0)])
        continue

    try:
        with open(utility_file, "r") as f:
            utility = int(f.read())
            private_utilities.append(utility)
        with open(placement_file, "r") as f:
            placement = json.loads(f.read())
            placements[sdo_name] = placement
        with open(rates_file, "r") as f:
            rates = OrderedDict(json.loads(f.read()))
            message_rates[sdo_name] = rates
    except FileNotFoundError:
        continue

# sum of private utilities
print("Sum of private utilities: " + str(sum(private_utilities)))

# print assignment info
placement_file = configuration.RESULTS_FOLDER + "/results.json"
with open(placement_file, "w") as f:
    f.write(json.dumps(placements, indent=4))
residual_resources = dict(rap.available_resources)
for service, function, node in list(itertools.chain(*placements.values())):
    residual_resources[node] = rap.sub_resources(residual_resources[node], rap.consumption[function])
total_residual_resources = {r: sum([residual_resources[n][r] for n in rap.nodes]) for r in rap.resources}
total_residual_resources_percentage = sum([total_residual_resources[r]/total_resources[r] for r in rap.resources])/len(rap.resources)
used_resources_percentage = 1 - total_residual_resources_percentage
print("Allocation: \n" + pprint.pformat(placements))
print("Residual resources: \n" + pprint.pformat(residual_resources))
print("Percentage of assigned resources: " + str(round(used_resources_percentage, 3)))
print("Percentage of successfully allocated bundles: " + str(round(len([u for u in private_utilities
                                                                        if u > 0]), 3)/configuration.SDO_NUMBER))

# calculate message rates
begin_time = min([float(next(iter(message_rates[sdo])).split(":")[0]) for sdo in message_rates])
next_begin_time = begin_time
global_rates = OrderedDict()
while len(message_rates) > 0:
    # next_begin_time = min([float(next(iter(message_rates[sdo])).split(":")[0]) for sdo in message_rates])
    # next_end_time = max([float(next(iter(message_rates[sdo])).split(":")[1]) for sdo in message_rates])
    next_end_time = next_begin_time+configuration.SAMPLE_FREQUENCY
    in_range_counter = 0
    for sdo in message_rates:
        if len(message_rates[sdo]) > 0:
            # in_range_keys = [k for k in message_rates[sdo] if float(k.split(":")[0]) >= next_begin_time and float(k.split(":")[1]) <= next_end_time]
            in_range_keys = [k for k in message_rates[sdo] if float(k.split(":")[1]) <= next_end_time]
            in_range_counter += sum([message_rates[sdo][k] for k in in_range_keys])
            for k in in_range_keys:
                del message_rates[sdo][k]
    for sdo in dict(message_rates):
        if len(message_rates[sdo]) == 0:
            del message_rates[sdo]
    global_rates[float("{0:.3f}".format(next_end_time-begin_time))] = in_range_counter/(next_end_time-next_begin_time)
    next_begin_time = next_end_time

# print message rates
print("Message rates: \n" + pprint.pformat(global_rates))

# purge rabbitmq queues
purge_rabbit.purge_queues(sdos)
