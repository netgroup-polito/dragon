#!/bin/bash

node_number=100
iterations=3

# NONE | MANY-NODES | FEW-NODES
policy="NONE"

rm -r -f validation/
mkdir validation

while [[ ${node_number} -le 400 ]]; do

    agents_number=50
    while [[ ${agents_number} -le 300 ]]; do

        # increase timeout according with the problem size
        # agreement_timeout=$(($((50*${bundle_percentage}/80 + 30*${agents_number}/30 + 20*${node_number}/4))/10))
        # # agreement_timeout=$(($(($((50*${bundle_percentage}/60 + 30*${agents_number}/10 + 20*${node_number}/4))/10))/2))
        # weak_agreement_timeout=$((${agreement_timeout}*2))
        # sed -i "/\bagreement_timeout\b/c\agreement_timeout = ${agreement_timeout}" ${CONFIG_FILE}
        # sed -i "/weak_agreement_timeout/c\weak_agreement_timeout = ${weak_agreement_timeout}" ${CONFIG_FILE}

        # output some info
        echo -e "Running setup with "${agents_number}" sdos, "${node_number}" nodes, "${iterations}" iterations ..."
        file_name="validation/"${agents_number}"sdos__"${node_number}"nodes.txt"

        # run the setup
        # python3 -m scripts.message_monitor &
        # monitor_pid=$!
        python3 -m tests.test_multi_large_scale ${agents_number} ${node_number} ${iterations} &> ${file_name}
        # kill -2 ${monitor_pid}
        # wait ${monitor_pid}
        killall python3
        # kill -9 ${monitor_pid}

        agents_number=$((${agents_number}+50))
    done
    node_number=$((${node_number}+100))
done
cp *.dat validation/
