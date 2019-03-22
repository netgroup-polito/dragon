## DRAGON v1.0 README

Updated March 22, 2019


#### @Copyright
DRAGON is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
DRAGON is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with DRAGON. If not, see <http://www.gnu.org/licenses/>.


#### About the project

This repository provides the prototype of an architecture that cenables coexistence of different applications over the same shared edge infrastructure. To dynamically partition resources to applications, this project uses the Distributed Resource AssiGnment OrchestratioN (DRAGON), an approximation algorithm that we designed to seek optimal resource partitioning between applications and guarantees both a bound on convergence time and an optimal (1-1/e)-approximation with respect to the Pareto optimal resource assignment.


#### Repository Structure

The repository tree contains: 


* [README.md]()  
    --this file  
* [LICENSE]()  
    --GPLv3 license  
* [main.py]()  
    --main instance executable  
* [config/]()  
    --configuration files  
* [dragon\_agent/]()  
    --DRAGON agent source files  
* [resource\_assignment/]()  
    --implementation of the applications-resources assignment problem  
* [scripts/]()  
    --useful scripts related to the project  
* [tests/]()  
    --validation purpose scripts  
* [use\_cases\_simulations/]()  
    --simulation environment that runs two edge use case over DRAGON

### Fetch

Download the source code by cloning the repository, as well as any submodule:

    $ git clone https://github.com/netgroup-polito/dragon
    $ cd dragon
    $ git submodule update --init

### Configuration

[config/config.py]() -- agent and instance configuration  
[config/rap\_instance.json]() -- resource assignment problem instance values


### Install

This project requires python 3.6 and has been tested on Linux debian (testing) with kernel 4.16.0-2-amd64.

Some additional python packages are required:

    $ sudo apt install python3-pip
    $ sudo pip3 install -r requirements.txt
    
Some tests require the metis library, please install it from source:	

    $ cd [dragon]/tests/utils/nxmetis
    # python3 setup.py install	

    
Inter agent communication is implemented over the RabbitMQ Broker. To install it use the following command: 

    # apt install rabbitmq-server
    
### Rabbit Federation

To use Federation, RabbitMQ Broker must be configured with a User, Policy and Federation Upstreams.

First of all install Federation Plugin:

    $ sudo /usr/sbin/rabbitmq-plugins enable rabbitmq_federation rabbitmq_federation_management

then restart RabbitMQ.

In order to setup the federation between the different RabbitMQ servers, you will need to a bit of command
line work on each of the servers.

Setup a new user and modify the [config/config.ini]() file with the chosen credentials:

    $ sudo rabbitmqctl add_user username password
    $ sudo rabbitmqctl set_user_tags username administrator
    $ sudo rabbitmqctl set_permissions -p / username ".*" ".*" ".*"

Then for example, on rabbit1 Broker, federate to 2 and 3:

    $ sudo rabbitmqctl set_parameter federation-upstream rabbit2 '{"uri":"amqp://username:password@10.0.0.1"}'
    $ sudo rabbitmqctl set_parameter federation-upstream rabbit3 '{"uri":"amqp://username:password@10.0.0.2"}'
    $ sudo rabbitmqctl set_parameter federation-upstream-set sdo '[{"upstream":"rabbit2"},{"upstream":"rabbit3"}]'
    $ sudo rabbitmqctl set_policy --apply-to exchanges federate-sdo ".*sdo.*" '{"federation-upstream-set":"sdo"}'

This does the following:

* Define two upstream nodes (named rabbit2 and rabbit3) and assign them the correct addresses. Then build an upstream-set
  called 'sdo' that contains those two nodes
* Create a policy (called 'federate-sdo') that selects all exchange whose name contains 'sdo' and federate them to the
  upstream-set 'sdo'

You will need to run a similar set of commands on each node to connect them as well.

All this can be done from the RabbitMQ Web UI by activating the plugin 'rabbitmq_management':

    $ sudo /usr/sbin/rabbitmq-plugins enable rabbitmq_management

The RabbitMQ Web UI are available on http://localhost:15672.



### Run

Make sure rabbitmq is running:

    # service rabbitmq-server start

The [main.py]() script runs a single instance of the DRAGON agent. To run it, use the following command from the project root directory:

    $ python3 main.py {agent-name} {services} [-d {configuration-file}]
    
where:

- ***agent-name***: is a name to identify the agent;
- ***services***: is a list of parameters, namely the names of services for which the agent will attempt to obtain resources (see [config/rap\_instance.json]()).
- ***configuration-file***: is the path of the configuration file to use (default is [config/default-config.ini]()).


#### Testing

The [tests/]() folder also contains a script that automatically runs multiple agents at the same time. 
Please modify [config/default-config.ini]() as desired before to run it, so to specify instance parameters, then use:

    $ python3 -m tests.test_script
    
The number of agent specified in the configuration file (each with a random number of services) will be run and the script will wait for convergence.
At the end of the execution, the log file of each agent will be available in the main folder, while details on the resulting assignments will be stored on the (generated) [results]() folder.

##### Tests on multiple remote hosts
 
An alternative script allows you to perform tests while running agents on remote hosts. 
Since this requires to setup ssh connections with the remote hosts, please install the ssh server on each of them:
 
    # apt install openssh-server
 
then please setup your ssh public key to be accepted on every target host.

You may need to increase the limit of ssh connections accepted on each host, by modifying the 'MaxStartups' parameter in the sshd configuration file:

    # nano /etc/ssh/sshd_config
    
Then, assuming you want to allow up to 50 connections, change the 'MaxStartups' line as follows:

    MaxStartups 50:30:100
    
Close and save the file, then restart the ssh daemon:

    # service sshd restart

Make sure rabbitmq is running on every host thorugh federated setup (see [https://www.rabbitmq.com/federation.html]()).

The [tests/test_script_ssh.py]() script can be setup specifying the list of remote hosts, the username to be used for the ssh connections and the remote path where dragon is located. Please modify these values in the first lines of the script according to your setup.

Analogously to the local test script, you can run the remote test using: 
   
    $ python3 -m tests.test_script_ssh
    
The script will automatically copy the local configuration to the remote hosts, and dragon agents will be spanned on them (agents that are neighbors in the topology file will be likely deployed on the same - or on a near - host). All output and log files will be fetched and results displayed locally.
