from __future__ import print_function

import multiprocessing
import sys
import hashlib
import json
import pprint
import shutil
import os
import time
import zipfile
# import threading
import socket

import paramiko
import itertools

from collections import OrderedDict
from subprocess import TimeoutExpired
from scp import SCPClient

from config.config import Configuration
from resource_assignment.resource_assignment_problem import ResourceAllocationProblem
from tests.utils.graph import Graph


# -------- Remote Test Configuration -------- #

# list of the remote hosts network addresses
remote_hosts = ["127.0.0.1"]
# remote username for ssh
remote_username = "gabriele"
# location of the dragon main folder on the remote hosts (both relative and absolute paths are ok)
remote_dragon_path = "dragon"
# local configuration file (will be copied on remote hosts)
CONF_FILE = 'config/config.ini'

# ------------------------------------------- #


def remote_sdo_worker(_host_index, _sdo_name, _services, _log_level, _conf_file):

    ssh_clients[_sdo_name] = paramiko.SSHClient()

    _ssh = ssh_clients[_sdo_name]
    _ssh.load_system_host_keys()
    _ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    _ssh.connect(remote_hosts[_host_index], username=remote_username)
    # time.sleep(3)

    try:
        _stdin, _stdout, _stderr = _ssh.exec_command("cd {}".format(remote_dragon_path) + "; "
                                                     "python3 main.py {} {} -l {} -d {} -o".format(_sdo_name,
                                                                                                   " ".join(_services),
                                                                                                   _log_level,
                                                                                                   _conf_file),
                                                     get_pty=True, timeout=50)
        _exit_status = stdout.channel.recv_exit_status()

        lines = _stdout.readlines()
        for line in lines:
            print(line)
        lines = _stderr.readlines()
        for line in lines:
            print(line, file=sys.stderr)
    except socket.timeout:
        _ssh.close()
        exit(1)

    _ssh.close()
    exit(0)


ssh_clients = dict()
p_list = list()

# [ Configuration ]
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

sdos.remove("sdo2")
sdos.append("ciccio")

# update problem instance according with configuration size
rap.sdos = sdos
rap.nodes = nodes

rap.available_resources = dict()
known_resources_units = {"cpu": 1, "memory": 512, "bandwidth": 256, "storage": 128}

known_ones = 0
if set(rap.resources) == {"cpu", "memory", "bandwidth"}:
    rap.available_resources["node0"] = {"cpu": 16, "memory": 4096, "bandwidth": 2048}
    if len(rap.nodes) > 1:
        rap.available_resources["node1"] = {"cpu": 12, "memory": 4096, "bandwidth": 2048}
    if len(rap.nodes) > 2:
        rap.available_resources["node2"] = {"cpu": 12, "memory": 8192, "bandwidth": 4096}
    if len(rap.nodes) > 3:
        rap.available_resources["node3"] = {"cpu": 4, "memory": 2048, "bandwidth": 1024}
    known_ones = 4

for node in rap.nodes[known_ones:]:
    node_resources = {resource: 2**(int(hashlib.sha256(str(node).encode()).hexdigest(), 16) % 5)
                      * known_resources_units.get(resource, 1)
                      for resource in rap.resources}
    rap.available_resources[node] = node_resources


with open(configuration.RAP_INSTANCE, mode="w") as rap_file:
    rap_file.write(json.dumps(rap.to_dict(), indent=4))

# prepare remote hosts
print("preparing remote hosts")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.load_system_host_keys()

for address in remote_hosts:
    ssh.connect(address, username=remote_username)

    command = ""
    # kill any old process
    if address != 'localhost' and address != '127.0.0.1':
        command += 'killall python3; '

    # purge rabbitmq queues
    command += 'cd {}'.format(remote_dragon_path) + '; ' + 'python3 -m scripts.purge_rabbit; '

    # copy configuration, instance and topology
    scp = SCPClient(ssh.get_transport())
    scp.put([CONF_FILE, configuration.RAP_INSTANCE],
            remote_dragon_path + "/config/")
    scp.close()

    # clean result directories
    command += 'rm -r {}'.format(configuration.RESULTS_FOLDER)
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {} {}".format(stdin, stdout.readlines(), stderr.readlines(), exit_status))

    ssh.close()

# clean result directory
shutil.rmtree(configuration.RESULTS_FOLDER, ignore_errors=True)

# load the 'sdo topology'
with open(configuration.TOPOLOGY_FILE) as topology_file:
    graph = Graph(json.load(topology_file), len(rap.sdos))
graph.print_topology()

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
used_hosts = set()
sdo_distribution = graph.compute_clusters(min(len(rap.sdos), len(remote_hosts)))
print("sdo distribution: {}".format(sdo_distribution))

print("- Run Orchestration - ")

for sdo in rap.sdos:
    # sdo_name = "sdo" + str(i)
    sdo_name = sdo
    service_bundle = [s for s in rap.services
                      if int(str(int(hashlib.sha256((sdo_name+s).encode()).hexdigest(), 16))[-2:]) < configuration.BUNDLE_PERCENTAGE]
    if len(service_bundle) == 0:
        service_bundle.append(rap.services[0])
    print(sdo_name + " : " + str(service_bundle))

    # run sdo instance on a physical node
    host = "node" + str(sdo_distribution[sdo_name])
    used_hosts.add(remote_hosts[sdo_distribution[sdo_name]])
    print("running instance " + sdo_name + " on host " + str(sdo_distribution[sdo_name]))

    # t = threading.Thread(target=remote_sdo_worker, args=(host,
    t = multiprocessing.Process(target=remote_sdo_worker, args=(sdo_distribution[sdo_name],
                                                                sdo_name,
                                                                service_bundle,
                                                                configuration.LOG_LEVEL,
                                                                CONF_FILE))
    t.start()

    p_list.append(t)

killed = list()
timeout = 100
step_time = time.time()
for i, t in enumerate(p_list):
    try:
        t.join(timeout=timeout)
        if t.exitcode == 1:
            print("WARNING: Forced agent '{}' to terminate. Possible incomplete output".format(rap.sdos[i]))
            killed.append('sdo' + str(i))
    except TimeoutExpired:
        t.terminate()
        print("WARNING: Forcing agent '{}' to terminate. Possible incomplete output".format(rap.sdos[i]))
        killed.append('sdo' + str(i))
    new_step_time = time.time()
    timeout -= new_step_time - step_time
    step_time = new_step_time
    timeout = max(timeout, 1)

print(" - Collect Results - ")

result_tmp_folder = "resultTmp"
if os.path.exists(result_tmp_folder+"/"+configuration.RESULTS_FOLDER):
    shutil.rmtree(result_tmp_folder+"/"+configuration.RESULTS_FOLDER)
if not os.path.exists(result_tmp_folder+"/"+configuration.RESULTS_FOLDER):
    os.makedirs(result_tmp_folder+"/"+configuration.RESULTS_FOLDER)

# fetch remote result files
for address in used_hosts:
    ssh.connect(address, username=remote_username)

    stdin, stdout, stderr = ssh.exec_command('cd {}/{}'.format(remote_dragon_path, configuration.RESULTS_FOLDER) + '; zip validation.zip *')
    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {} {}".format(stdin, stdout.readlines(), stderr.readlines(), exit_status))

    scp = SCPClient(ssh.get_transport())
    # results
    scp.get(remote_dragon_path+'/'+configuration.RESULTS_FOLDER+'/validation.zip', local_path=result_tmp_folder+"/"+configuration.RESULTS_FOLDER+"/")
    zip_ref = zipfile.ZipFile(result_tmp_folder+"/"+configuration.RESULTS_FOLDER+"/validation.zip", 'r')
    zip_ref.extractall(result_tmp_folder+"/"+configuration.RESULTS_FOLDER)
    zip_ref.close()
    os.remove(result_tmp_folder+"/"+configuration.RESULTS_FOLDER+"/validation.zip")
    # logs
    # for log_file in log_files:
    #    scp.get(remote_dragon_path + "/" + log_file)
    scp.close()
    ssh.close()

if os.path.exists(configuration.RESULTS_FOLDER):
    shutil.rmtree(configuration.RESULTS_FOLDER)

shutil.move(result_tmp_folder+"/"+configuration.RESULTS_FOLDER,os.getcwd())
shutil.rmtree(result_tmp_folder)

# fetch post process information
placements = dict()
message_rates = dict()
private_utilities = list()
sent_messages = dict()
last_update_times = list()
for sdo in rap.sdos:
    # sdo_name = "sdo" + str(i)
    sdo_name = sdo
    results_file = configuration.RESULTS_FOLDER + "/results_" + sdo_name + ".json"

    if sdo_name in killed:
        private_utilities.append(0)
        last_update_times.append(0)
        placements[sdo_name] = []
        # message_rates[sdo_name] = OrderedDict([("0:0", 0)])
        sent_messages[sdo_name] = 0
        continue

    try:
        with open(results_file) as f:
            results = json.loads(f.read())
            private_utilities.append(results["utility"])
            last_update_times.append(results["last-update"])
            placements[sdo_name] = results["placement"]
            message_rates[sdo_name] = OrderedDict(results["rates"])
            sent_messages[sdo_name] = results["messages"]
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
print("Total messages sent: {}".format(sum(list(sent_messages.values()))))
print("Last update on {0:.3f}".format(max(last_update_times)))
print("Timeout on: {}".format(killed))

'''
# purge rabbitmq queues
for address in remote_hosts:
    ssh.connect(address, username=remote_username)
    # purge rabbitmq queues
    stdin, stdout, stderr = ssh.exec_command('cd {}'.format(remote_dragon_path) + '; ' +
                                             'python3 -m scripts.purge_rabbit')
    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {} {}".format(stdin, stdout.readlines(), stderr.readlines(), exit_status))
    ssh.close()
'''
