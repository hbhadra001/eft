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

ROLE_ARN=$(aws iam get-role --role-name lambda-sftp-role --query 'Role.Arn' --output text)

aws lambda create-function \
  --function-name paramiko-sftp-fn \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.handler \
  --timeout 900 \
  --memory-size 1024 \
  --zip-file fileb://function.zip


  # Clean build
rm -rf package function.zip && mkdir -p package

# Install exact, prebuilt wheels for Lambda’s env
# (includes cffi explicitly)
pip3 install -t package --only-binary=:all: \
  cffi cryptography pynacl bcrypt paramiko

# Add your handler
cp lambda_function.py package/

# Create the deployment zip with correct layout (no extra top folder)
cd package && zip -r ../function.zip . && cd ..

# Update the function code
aws lambda update-function-code \
  --function-name YOUR_FUNCTION \
  --zip-file fileb://function.zip


python3 - <<'PY'
import pkgutil, sys
print("python:", sys.version)
print("_cffi_backend present:", pkgutil.find_loader("_cffi_backend") is not None)
PY



