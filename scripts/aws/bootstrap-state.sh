#!/usr/bin/env bash
set -euo pipefail

region="${AWS_REGION:-ap-southeast-2}"
bucket="${TF_STATE_BUCKET:-}"
if [[ -z "$bucket" ]]; then
  echo "Set TF_STATE_BUCKET to a globally unique, private S3 bucket name." >&2
  exit 2
fi

created=false
if aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
  echo "Verifying existing dedicated Terraform state bucket: $bucket"
else
  if [[ "$region" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$bucket" --region "$region"
  else
    aws s3api create-bucket --bucket "$bucket" --region "$region" \
      --create-bucket-configuration "LocationConstraint=$region"
  fi
  created=true
fi

if [[ "$created" == true ]]; then
  aws s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-versioning --bucket "$bucket" --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$bucket" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  policy="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"DenyInsecureTransport\",\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::$bucket\",\"arn:aws:s3:::$bucket/*\"],\"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
  aws s3api put-bucket-policy --bucket "$bucket" --policy "$policy"
else
  aws s3api get-public-access-block --bucket "$bucket" --query 'PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]' --output text | grep -q 'True.*True.*True.*True' || {
    echo "Existing bucket does not block all public access; refusing to change its configuration." >&2; exit 2;
  }
  aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text | grep -qx Enabled || {
    echo "Existing bucket versioning is not enabled; refusing to change its configuration." >&2; exit 2;
  }
  aws s3api get-bucket-encryption --bucket "$bucket" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text | grep -Eq 'AES256|aws:kms' || {
    echo "Existing bucket encryption is not enabled; refusing to change its configuration." >&2; exit 2;
  }
  aws s3api get-bucket-policy --bucket "$bucket" --query Policy --output text | grep -q 'DenyInsecureTransport' || {
    echo "Existing bucket policy lacks the TLS-only guard; refusing to change its policy." >&2; exit 2;
  }
fi
echo "Terraform state bucket is private, versioned, encrypted and TLS-only."
