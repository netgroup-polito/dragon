import json
from collections import OrderedDict


def cluster_topology(n_clusters, n_edges, edges_prefix):
    """

    :param n_clusters:
    :param n_edges:
    :param edges_prefix:
    :return:
    """
    sdos = list()
    for i in range(n_edges):
        sdos.append("{}{}".format(edges_prefix, i))
    cluster_labels = dict()
    clusters = [[] for i in range(n_clusters)]
    masters_per_cluster = max(1, int(n_edges/n_clusters/5))
    master_indexes = list()
    for i in range(masters_per_cluster):
        master_indexes.append(i*5)
    print("master_indexes: {}".format(master_indexes))

    for i, sdo in enumerate(sdos):
        n = i % n_clusters
        clusters[n].append(sdo)
        cluster_labels[sdo] = n

    print(clusters)

    topology = OrderedDict()
    for sdo in sdos:
        n = cluster_labels[sdo]
        topology[sdo] = [s for s in clusters[n] if s != sdo]

        for index in master_indexes:
            if clusters[n][index] == sdo:
                '''
                for other_index in master_indexes:
                    print([clusters[i][other_index] for i in range(len(clusters)) if clusters[i][other_index] != sdo])
                    topology[sdo].extend([clusters[i][other_index] for i in range(len(clusters)) if clusters[i][other_index] != sdo])
                '''
                topology[sdo].extend([clusters[i][index] for i in range(len(clusters)) if clusters[i][index] != sdo])
        topology[sdo].sort(key=lambda x: int(x.replace(edges_prefix, '')))

    return topology


if __name__ == "__main__":

    t_dict = cluster_topology(5, 200, "sdo")
    # print(t_dict)
    with open("topology_cluster.json", mode="w") as t_file:
        json.dump(t_dict, t_file)
