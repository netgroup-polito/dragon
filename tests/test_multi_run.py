from __future__ import print_function

import configparser
import copy
import multiprocessing
import random
import sys
import hashlib
import json
import pprint
import shutil
import os
import time
import zipfile
import socket

import paramiko
import itertools

from collections import OrderedDict
from subprocess import TimeoutExpired
from scp import SCPClient

from config.config import Configuration
from resource_assignment.resource_assignment_problem import ResourceAllocationProblem
from tests.utils.graph import Graph


# -------- Multi-run Test Configuration -------- #

# list of the remote hosts network addresses
remote_hosts = ["127.0.0.1"]
# remote username for ssh
remote_username = "gabriele"
# location of the dragon main folder on the remote hosts (both relative and absolute paths are ok)
remote_dragon_path = "dragon"
# local configuration file (will be copied on remote hosts)
CONF_FILE = 'config/config.ini'
# main topology file
MAIN_TOPOLOGY_FILE = 'config/topology.json'
# temporary topology file
TMP_TOPOLOGY_FILE = 'config/my_topology.json'

# ----------------------------------------------- #


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
                                                     get_pty=True, timeout=20)
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


# [ Simulation parameters ]
if len(sys.argv) != 4:
    print("usage python3 -m tests.test_multi_run <sdos_n> <nodes_n> <boh>")
    exit(1)

sdos_number = int(sys.argv[1])
nodes_number = int(sys.argv[2])
iterations = int(sys.argv[3])

sdos = ["sdo-"+str(n) for n in range(sdos_number)]
nodes = ["node" + str(n) for n in range(nodes_number)]
bundles = dict()
total_resources = None

print("Long run simulation")
print("Total number of sdos: {}".format(sdos_number))
print("Total number of nodes: {}".format(nodes_number))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.load_system_host_keys()

# [ Configuration ]
configuration = Configuration(CONF_FILE)

# [ RAP instance ]
rap = ResourceAllocationProblem()
with open(configuration.RAP_INSTANCE, mode="r") as rap_file:
    rap.parse_dict(json.loads(rap_file.read()))

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

for sdo in sdos:
    service_bundle = [s for s in rap.services
                      if int(str(int(hashlib.sha256((sdo+s).encode()).hexdigest(), 16))[-2:]) < configuration.BUNDLE_PERCENTAGE]
    if len(service_bundle) == 0:
        service_bundle.append(rap.services[0])
    elif len(service_bundle) >= 2*configuration.BUNDLE_PERCENTAGE:
        service_bundle.pop()
    bundles[sdo] = service_bundle
    print(sdo + " : " + str(service_bundle))

deployed = set()
overall_placements = {sdo: [] for sdo in sdos}
last_bundles = copy.deepcopy(bundles)
total_resources = copy.deepcopy(rap.available_resources)
random.seed(123456)
delete_probability = {sdo: 0 for sdo in sdos}
deploy_probability = {sdo: 5 for sdo in sdos}
update_probability = {sdo: 0 for sdo in sdos}

convergence_times = list()
convergence_messages = list()
concurrency = list()

iteration = 0
while iteration < iterations:

    iteration += 1

    print(" - Iteration {} - ".format(iteration))

    print(" - \n - Deployed: {}".format(deployed))
    print(" - \n - Placements: {}\n - ".format(overall_placements))

    print("Delete probabilities: {}".format(delete_probability.values()))
    print("Deploy probabilities: {}".format(deploy_probability.values()))
    print("Update probabilities: {}".format(update_probability.values()))

    # ---------------------------------------------- SETUP ITERATION ------------------------------------------------- #

    # [ simulate apps to be deleted ]
    to_delete = [sdo for sdo in deployed if sdo in deployed and random.uniform(0, 100) < delete_probability[sdo]]
    # free resources for deleted apps
    # to_delete_placements = {k: v for k, v in overall_placements.items() if k in to_delete}
    # for service, function, node in list(itertools.chain(*to_delete_placements.values())):
    #     rap.available_resources[node] = rap.sum_resources(rap.available_resources[node], rap.consumption[function])
    for sdo in to_delete:
        overall_placements[sdo] = []
        deployed.remove(sdo)

    # [ simulate apps to be deployed ]
    to_deploy = [sdo for sdo in sdos if sdo not in to_delete and sdo not in deployed
                 and random.uniform(0, 100) < deploy_probability[sdo]]

    # [ simulate apps to be updated ]
    to_update = [sdo for sdo in deployed if sdo not in to_delete
                 and random.uniform(0, 100) < update_probability[sdo]]

    flag = True
    while len(to_deploy + to_update) > 30:
        if flag:
            to_update.pop()
        else:
            to_deploy.pop()
        flag = not flag

    updated_bundles = dict()
    diff_bundles = dict()
    del_bundles = dict()
    for sdo in to_update[:]:
        services_to_update = list()
        services_to_update.append(last_bundles[sdo][random.randrange(0, len(last_bundles[sdo]))])
        for s in last_bundles[sdo]:
            if s not in services_to_update and random.uniform(0, 100) < 10:
                services_to_update.append(s)
        remove_threshold = 40
        scale_threshold = 80
        len_change_factor = len(bundles[sdo])/len(last_bundles[sdo])
        remove_threshold = remove_threshold*len_change_factor
        updated_bundles[sdo] = list(last_bundles[sdo])
        for s in services_to_update:
            update_type = random.uniform(0, 100)  # choice should keep bundle around the same length
            if update_type <= remove_threshold:  # remove
                updated_bundles[sdo].remove(s)
            elif update_type <= scale_threshold:  # scale out
                updated_bundles[sdo].append(s)
            else:  # replace
                updated_bundles[sdo].remove(s)
                updated_bundles[sdo].append(rap.services[random.randrange(0, len(rap.services))])
        del_bundles[sdo] = list(last_bundles[sdo])
        diff_bundles[sdo] = list(updated_bundles[sdo])
        for s in diff_bundles[sdo][:]:
            if s in del_bundles[sdo]:
                del_bundles[sdo].remove(s)
                diff_bundles[sdo].remove(s)
        if len(diff_bundles[sdo]) == 0:
            if len(updated_bundles[sdo]) == 0:
                to_delete.append(sdo)
            last_bundles[sdo] = updated_bundles[sdo]
            diff_bundles.pop(sdo)
            updated_bundles.pop(sdo)
            to_update.remove(sdo)

    # delete the new to_delete ones
    for sdo in dict(del_bundles):
        if sdo in to_delete:
            for service, function, node in overall_placements[sdo][:]:
                if service in del_bundles[sdo]:
                    # rap.available_resources[node] = rap.sum_resources(rap.available_resources[node], rap.consumption[function])
                    overall_placements[sdo].remove((service, function, node))
            del_bundles.pop(sdo)
            overall_placements[sdo] = []
            deployed.remove(sdo)

    # [ Iteration stats ]
    # missing stats for updated sdo with empty diff (only release)
    print("DELETED:              " + str(to_delete))
    print("TO DEPLOY:            " + str(to_deploy))
    print("TO UPDATE:            " + str(to_update))

    for sdo in to_update:
        print("{}: {} -> {}".format(sdo, last_bundles[sdo], updated_bundles[sdo]))

    # update rap instance (resources and sdos)
    for node in rap.nodes:
        rap.available_resources[node] = total_resources[node]
    for service, function, node in list(itertools.chain(*overall_placements.values())):
        rap.available_resources[node] = rap.sub_resources(rap.available_resources[node], rap.consumption[function])
    rap.sdos = to_deploy + to_update
    with open(configuration.RAP_INSTANCE, mode="w") as rap_file:
        rap_file.write(json.dumps(rap.to_dict(), indent=4))

    # update topology
    with open(MAIN_TOPOLOGY_FILE, mode="r") as main_t_f, open(TMP_TOPOLOGY_FILE, mode="w") as t_f:
        topology_s = main_t_f.read()
        for i, sdo in enumerate(rap.sdos):
            topology_s = topology_s.replace('"sdo{}"'.format(i), '"{}"'.format(sdo))
        t_f.write(topology_s)

    # update configuration file
    parser = configparser.ConfigParser()
    parser.read(CONF_FILE)
    parser.set("problem_size", 'agents_number', str(len(rap.sdos)))
    parser.set("problem_size", 'nodes_number', str(len(rap.nodes)))
    parser.set("neighborhood", 'topology_file', TMP_TOPOLOGY_FILE)
    with open(CONF_FILE, mode="w") as conf_file:
        parser.write(conf_file)

    # -------------------------------------------------- RUN --------------------------------------------------------- #

    ssh_clients = dict()
    p_list = dict()
    killed = list()

    if len(rap.sdos) > 0:

        # prepare remote hosts
        print("preparing remote hosts")

        for address in remote_hosts:
            ssh.connect(address, username=remote_username)

            command = ""
            # kill any old process
            if address != 'localhost' and address != '127.0.0.1':
                command += 'killall python3; '

            # purge rabbitmq queues
            command += 'cd {}; '.format(remote_dragon_path)
            command += 'python3 -m scripts.purge_rabbit -d {} -q {}; '.format(CONF_FILE, " ".join(sdos))

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

        # print total resources
        merged_resources = rap.get_total_resources_amount()
        average_resource_per_function = {r: sum([rap.get_function_resource_consumption(f)[r] for f in rap.functions])/len(rap.functions) for r in rap.resources}
        average_resource_percentage_per_function = sum([average_resource_per_function[r]/merged_resources[r] for r in rap.resources])/len(rap.resources)
        statistical_bundle_len = len(rap.services)*(configuration.BUNDLE_PERCENTAGE/100)
        average_resource_demand = statistical_bundle_len*average_resource_percentage_per_function
        print("- Resources Statistics - ")
        print("Total resources: \n" + pprint.pformat(merged_resources))
        # print("Average resources per function: \n" + pprint.pformat(average_resource_per_function))
        # print("Average demand percentage per function: " + str(round(average_resource_percentage_per_function, 3)))
        print("Statistical bundle len: " + str(round(statistical_bundle_len, 2)))
        # print("Statistical average demand percentage per bundle: " + str(round(average_resource_demand, 3)))
        print("Statistical total demand percentage: " + str(round(average_resource_demand*configuration.SDO_NUMBER, 3)))
        print("- -------------------- - ")

        # load the 'sdo topology'
        with open(TMP_TOPOLOGY_FILE) as topology_file:
            graph = Graph(json.load(topology_file), len(rap.sdos))
        graph.print_topology()

        # distribute sdos among physical nodes
        used_hosts = set()
        sdo_distribution = graph.compute_clusters(min(len(rap.sdos), len(remote_hosts)))
        print("sdo distribution: {}".format(sdo_distribution))

        print("- Run Orchestration - ")

        for sdo in rap.sdos:
            if sdo in to_deploy:
                service_bundle = bundles[sdo]
            elif sdo in to_update:
                service_bundle = diff_bundles[sdo]
            else:
                print("WARNING: wrong sdo in rap problem")
                iteration -= 1
                continue

            print("{} : {}".format(sdo, service_bundle))

            # run sdo instance on a physical node
            host = "node" + str(sdo_distribution[sdo])
            used_hosts.add(remote_hosts[sdo_distribution[sdo]])
            print("running instance " + sdo + " on host " + str(sdo_distribution[sdo]))

            # t = threading.Thread(target=remote_sdo_worker, args=(host,
            t = multiprocessing.Process(target=remote_sdo_worker, args=(sdo_distribution[sdo],
                                                                        sdo,
                                                                        service_bundle,
                                                                        configuration.LOG_LEVEL,
                                                                        CONF_FILE))
            t.start()

            p_list[sdo] = t

        killed = list()
        timeout = 100
        step_time = time.time()
        for sdo, t in p_list.items():
            try:
                t.join(timeout=timeout)
                if t.exitcode == 1:
                    print("WARNING: Forced agent '{}' to terminate. Possible incomplete output".format(sdo))
                    killed.append(sdo)
            except TimeoutExpired:
                t.terminate()
                print("WARNING: Forcing agent '{}' to terminate. Possible incomplete output".format(sdo))
                killed.append(sdo)
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

        shutil.move(result_tmp_folder+"/"+configuration.RESULTS_FOLDER, os.getcwd())
        shutil.rmtree(result_tmp_folder)
    else:
        iteration -= 1

    # ------------------------------------------------- FETCH ---------------------------------------------------------#

    # fetch post process information
    placements = dict()
    message_rates = dict()
    private_utilities = list()
    sent_messages = dict()
    last_update_times = list()
    winners = list()
    agreement_times = dict()
    if killed:
        print("skipping...")
        iteration -= 1
        continue

    if len(rap.sdos) > 0:
        for sdo in rap.sdos:
            # sdo_name = "sdo" + str(i)
            sdo_name = sdo
            results_file = configuration.RESULTS_FOLDER + "/results_" + sdo_name + ".json"

            if sdo_name in killed:
                private_utilities.append(0)
                last_update_times.append(0)
                agreement_times[sdo_name] = 0
                placements[sdo_name] = []
                # message_rates[sdo_name] = OrderedDict([("0:0", 0)])
                sent_messages[sdo_name] = 0
                continue

            try:
                with open(results_file) as f:
                    results = json.loads(f.read())
                    private_utilities.append(results["utility"])
                    last_update_times.append(results["last-update"])
                    agreement_times[sdo_name] = results["agreement"]
                    placements[sdo_name] = results["placement"]
                    message_rates[sdo_name] = OrderedDict(results["rates"])
                    sent_messages[sdo_name] = results["messages"]
                    if placements[sdo]:
                        winners.append(sdo)

            except FileNotFoundError:
                continue

        # update resources
        for sdo in placements:
            overall_placements[sdo] = placements[sdo]
        for node in rap.nodes:
            rap.available_resources[node] = total_resources[node]
        for service, function, node in list(itertools.chain(*overall_placements.values())):
            rap.available_resources[node] = rap.sub_resources(rap.available_resources[node], rap.consumption[function])
        with open(configuration.RAP_INSTANCE, mode="w") as rap_file:
            rap_file.write(json.dumps(rap.to_dict(), indent=4))

        # sum of private utilities
        print("Sum of private utilities: " + str(sum(private_utilities)))

        # print assignment info
        placement_file = configuration.RESULTS_FOLDER + "/results.json"
        with open(placement_file, "w") as f:
            f.write(json.dumps(placements, indent=4))
        merged_resources = rap.get_total_resources_amount()
        total_residual_resources = {r: sum([rap.available_resources[n][r] for n in rap.nodes]) for r in rap.resources}
        total_residual_resources_percentage = sum([total_residual_resources[r]/merged_resources[r] for r in rap.resources])/len(rap.resources)
        used_resources_percentage = 1 - total_residual_resources_percentage
        print("Allocation: \n" + pprint.pformat(placements))
        print("Residual resources: \n" + pprint.pformat(rap.available_resources))
        print("Percentage of assigned resources: " + str(round(used_resources_percentage, 3)))
        print("Percentage of successfully allocated bundles: " + str(round(len([u for u in private_utilities
                                                                                if u > 0]), 3)/configuration.SDO_NUMBER))
        print("Total messages sent: {}".format(sum(list(sent_messages.values()))))
        print("Last update on {0:.3f}".format(max(last_update_times)))
        print("Last agreement on {0:.3f}".format(max(agreement_times.values())))
        print("Agreement is week on: {}".format([sdo for sdo in agreement_times if agreement_times[sdo] == 0]))
        print("Timeout on: {}".format(killed))

        convergence_times.append(max(last_update_times + [0]))
        convergence_messages.append(sum(list(sent_messages.values())))
        concurrency.append(len(rap.sdos))

    # ------------------------------------------------ SETUP NEXT ---------------------------------------------------- #

    for sdo in winners:
        deployed.add(sdo)
        if sdo in to_deploy:
            last_bundles[sdo] = bundles[sdo]
        elif sdo in to_update:
            last_bundles[sdo] = updated_bundles[sdo]
        else:
            print("WARNING: wrong sdo in winners list")

    # [ update simulation probabilities ]
    unit = 5
    for sdo in sdos:
        if sdo in to_delete:
            delete_probability[sdo] = 0
            deploy_probability[sdo] = 0
            update_probability[sdo] = 0
        elif sdo in winners:
            if sdo in to_deploy:
                delete_probability[sdo] = unit*random.randrange(3)
                deploy_probability[sdo] = 0
                update_probability[sdo] = 0
            elif sdo in to_update:
                deploy_probability[sdo] = 0
                update_probability[sdo] = 0
                delete_probability[sdo] += unit
        elif sdo in deployed:
            delete_probability[sdo] += unit*2
            deploy_probability[sdo] = 0
            update_probability[sdo] += unit*random.randrange(5)
            if sdo in to_update:
                delete_probability[sdo] = 50
                deploy_probability[sdo] = 0
                # update_probability[sdo] += unit
        elif sdo in to_deploy:
            delete_probability[sdo] = 0
            deploy_probability[sdo] = 0
            update_probability[sdo] = 0
        else:
            delete_probability[sdo] = 0
            deploy_probability[sdo] += unit*random.randrange(2)
            update_probability[sdo] = 0

        delete_probability[sdo] = max(delete_probability[sdo], 0)
        delete_probability[sdo] = min(delete_probability[sdo], 100)
        deploy_probability[sdo] = max(deploy_probability[sdo], 0)
        deploy_probability[sdo] = min(deploy_probability[sdo], 100)
        update_probability[sdo] = max(update_probability[sdo], 0)
        update_probability[sdo] = min(update_probability[sdo], 100)

for address in remote_hosts:
    ssh.connect(address, username=remote_username)
    # purge rabbitmq queues
    stdin, stdout, stderr = ssh.exec_command('cd {}'.format(remote_dragon_path) + '; ' +
                                             'python3 -m scripts.purge_rabbit -d {} -q {}'.format(CONF_FILE,
                                                                                                  " ".join(sdos)))
    exit_status = stdout.channel.recv_exit_status()
    print("{} {} {} {}".format(stdin, stdout.readlines(), stderr.readlines(), exit_status))
    ssh.close()

print("concurrency: {}".format(concurrency))
print("# {} sdos, {} nodes".format(len(sdos), len(nodes)))
print("# convergence")
print(" ".join(["{0:.3f}".format(t) for t in convergence_times]))
print("# messages")
print(" ".join(["{}".format(m) for m in convergence_messages]))
