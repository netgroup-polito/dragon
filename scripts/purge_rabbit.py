import pika

from config.config import Configuration


def purge_queues(queues):
    credentials = pika.PlainCredentials(configuration.USERNAME, configuration.PASSWORD)
    parameters = pika.ConnectionParameters('localhost', 5672, '/', credentials)

    connection = pika.BlockingConnection(parameters)

    #connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    for sdo in queues:
        channel.queue_declare(queue=sdo)
        channel.queue_purge(sdo)
        channel.queue_delete(queue=sdo)
    connection.close()

if __name__ == "__main__":
    configuration = Configuration()
    sdos = ["sdo" + str(n) for n in range(configuration.SDO_NUMBER)]
    purge_queues(sdos)
