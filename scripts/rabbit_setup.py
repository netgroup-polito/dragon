import os

from config.config import Configuration

def federation(username,password,peers):

    for peer in peers:
        federation_upstream = 'rabbitmqctl set_parameter federation-upstream ' + str(
            peer[0]) + ' \'{"uri":"amqp://'+username+':'+password+'@' + peer[1] + '"}\''
        cmd = os.popen(federation_upstream).read()
        print(cmd)

    federation_upstream_set = 'rabbitmqctl set_parameter federation-upstream-set '+configuration.SET_NAME+' \'['
    for peer in peers:
        federation_upstream_set = federation_upstream_set + '{"upstream":"' + str(peer[0]) + '"},'
    federation_upstream_set = federation_upstream_set + ']\''
    cmd = os.popen(federation_upstream_set).read()
    print(cmd)

    set_policy = 'rabbitmqctl set_policy --apply-to exchanges '+configuration.POLICY_NAME+' "'+configuration.PATTERN+'" \'{"federation-upstream-set":"'+configuration.SET_NAME+'"}\''
    cmd = os.popen(set_policy).read()
    print(cmd)

def new_rabbitMQ_user(username,password):

    add_user_command = 'rabbitmqctl add_user '+username+' '+password
    cmd = os.popen(add_user_command).read()
    print(cmd)
    set_user_tag = 'rabbitmqctl set_user_tags '+username+' administrator'
    cmd = os.popen(set_user_tag).read()
    print(cmd)
    set_permissions = 'rabbitmqctl set_permissions -p / '+username+' ".*" ".*" ".*"'
    cmd = os.popen(set_permissions).read()
    print(cmd)

if __name__ == '__main__':
    # [ Configuration ]
    CONF_FILE = 'config/default-config.ini'
    configuration = Configuration(CONF_FILE)

    username=configuration.USERNAME
    password=configuration.PASSWORD

    peers = [["rabbit1", "10.0.0.1"],["rabbit2","10.0.0.2"]]

    new_rabbitMQ_user(username=username,password=password)
    federation(username=username,password=password,peers=peers)