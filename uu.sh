mkdir -p layer/python
pip install -t layer/python --only-binary=:all: paramiko cryptography bcrypt pynacl
(cd layer && zip -r ../paramiko-layer.zip python)

# If you haven't built it yet:
mkdir -p layer/python
pip install -t layer/python --only-binary=:all: paramiko cryptography bcrypt pynacl
( cd layer && zip -r ../paramiko-layer.zip python )

# Publish the layer (replace REGION if needed)
aws lambda publish-layer-version \
  --layer-name paramiko-al2023 \
  --zip-file fileb://paramiko-layer.zip \
  --compatible-runtimes python3.12


mkdir -p package
pip install --only-binary=:all: -t package paramiko cryptography bcrypt pynacl
cp lambda_function.py package/
cd package && zip -r ../function.zip .

