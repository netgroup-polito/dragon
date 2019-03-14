import os
import paramiko


class SSHConnection:

    """
        Class for SFTP Connection using Paramiko
    """

    def __init__(self, host, username, key_file, path=None):

        paramiko.util.log_to_file('/tmp/paramiko.log')
        self.host = host
        self.port = 22
        #self.path = os.path.join(os.environ['HOME'], '.ssh', 'id_dsa')
        self.key_file = os.path.expanduser('key_file')
        self.key = paramiko.RSAKey.from_private_key_file(self.key_file)
        self.username = username

    def connect(self):

        """
            SFTP connection to 192.168.1.77 server using root user
        """
        transport = paramiko.Transport((self.host1, self.port))
        transport.connect(username = self.username, pkey = self.mykey)

        sftp = paramiko.SFTPClient.from_transport(transport)

        return sftp