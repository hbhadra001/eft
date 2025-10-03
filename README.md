ssh -vvv -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no \
    -o HostKeyAlgorithms=+ssh-rsa \
    user@<host> -p 22
