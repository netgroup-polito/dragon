import argparse
import json

import pika

from config.config import Configuration
from resource_assignment.resource_assignment_problem import ResourceAllocationProblem


def purge_queues(_queues, username, password):
    credentials = pika.PlainCredentials(username, password)
    parameters = pika.ConnectionParameters('localhost', 5672, '/', credentials)

    connection = pika.BlockingConnection(parameters)

    #connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    for sdo in _queues:
        channel.queue_declare(queue=sdo)
        channel.queue_purge(sdo)
        channel.queue_delete(queue=sdo)
    connection.close()


if __name__ == "__main__":
    configuration = Configuration()
    sdos = ["sdo" + str(n) for n in range(configuration.SDO_NUMBER)]
    purge_queues(sdos, configuration.USERNAME, configuration.PASSWORD)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-q',
        '--queues',
        type=str,
        nargs='+',
        help='List of additional queues to purge.',
    )
    parser.add_argument(
        '-d',
        '--conf-file',
        nargs='?',
        default='config/default_config.ini',
        help='Configuration file.'
    )
    args = parser.parse_args()
    additional_queues = list()
    if args.queues:
        additional_queues.extend(args.queues)

    configuration = Configuration(args.conf_file)

    with open(configuration.RAP_INSTANCE, mode="r") as enop_file:
        enop = ResourceAllocationProblem()
        enop.parse_dict(json.loads(enop_file.read()))
        sdos = ["{}".format(sdo) for sdo in enop.sdos]

    queues = []
    queues.extend(sdos)
    queues.extend(additional_queues)
    purge_queues(queues, configuration.USERNAME, configuration.PASSWORD)