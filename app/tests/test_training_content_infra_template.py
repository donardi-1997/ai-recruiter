"""Offline CloudFormation contracts for training-media infrastructure."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "infra" / "training-content.yml"


def _template() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_training_content_bucket_is_private_encrypted_and_dedicated():
    template = _template()
    bucket = template["Resources"]["TrainingContentBucket"]["Properties"]

    assert bucket["BucketName"] == {
        "Fn::Sub": "ai-recruiter-training-${AWS::AccountId}-${AWS::Region}"
    }
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    assert bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"]


def test_training_content_cors_is_explicit_for_upload_and_playback():
    template = _template()
    rule = template["Resources"]["TrainingContentBucket"]["Properties"][
        "CorsConfiguration"
    ]["CorsRules"][0]

    assert set(rule["AllowedMethods"]) == {"POST", "GET", "HEAD"}
    assert "*" not in rule["AllowedOrigins"]
    assert "https://ai.adrianguerra.net" in rule["AllowedOrigins"]
    assert "https://dzcwl3yhv133t.cloudfront.net" in rule["AllowedOrigins"]


def test_training_content_policy_is_runtime_role_scoped_and_prefix_limited():
    template = _template()
    statements = template["Resources"]["TrainingContentBucketPolicy"]["Properties"][
        "PolicyDocument"
    ]["Statement"]

    assert statements
    for statement in statements:
        assert statement["Principal"] == {"AWS": {"Ref": "RuntimeRoleArn"}}
        assert statement["Resource"] != "*"
        assert "training/*" in str(statement["Resource"])

    actions = {
        action
        for statement in statements
        for action in statement["Action"]
    }
    assert actions == {
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    }


def test_training_content_template_exposes_bucket_output():
    template = _template()
    assert template["Parameters"]["RuntimeRoleArn"]["Type"] == "String"
    assert template["Outputs"]["TrainingContentBucket"]["Value"] == {
        "Ref": "TrainingContentBucket"
    }
