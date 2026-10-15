#!/bin/sh
# Package and update an existing Lambda function. Does not create AWS resources.
set -eu
cd "$(dirname "$0")/.."
FUNCTION_NAME="${CLAUSE_CHECK_FUNCTION:-clause-check}"
REGION="${AWS_REGION:-eu-west-2}"
rm -rf build clause-check.zip
mkdir -p build
python3 -m pip install -r requirements-lambda.txt -t build
cp -R app corpus build/
rm -rf build/app/api build/app/main.py
python3 - << 'PY'
import pathlib
root = pathlib.Path("build")
for path in root.rglob("__pycache__"):
    for child in path.rglob("*"):
        if child.is_file():
            child.unlink()
    path.rmdir()
PY
(
  cd build
  zip -qr ../clause-check.zip .
)
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file fileb://clause-check.zip \
  --region "$REGION"
echo "updated $FUNCTION_NAME in $REGION"
