mkdir -p layer/python
pip install -t layer/python --only-binary=:all: paramiko cryptography bcrypt pynacl
(cd layer && zip -r ../paramiko-layer.zip python)
