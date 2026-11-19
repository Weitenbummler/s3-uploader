"""Verbindungstest gegen eine S3-Attrappe mit echter Signatur- und Rechteprüfung (moto IAM)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws
from moto.core import set_initial_no_auth_action_count

from s3_uploader.client import erzeuge_client
from s3_uploader.konfiguration import Verbindung
from s3_uploader.verbindungstest import Stufe, teste_verbindung

ENDPUNKT = "https://s3.amazonaws.com"
BUCKET = "iam-bucket"

# Konto darf nur unter "upload/" schreiben – nicht auflisten, nicht löschen.
NUR_SCHREIBEN = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{BUCKET}/upload/*",
        }
    ],
}


@pytest.fixture
def schluessel() -> Iterator[dict[str, str]]:
    """Legt Bucket und ein IAM-Konto mit reinem Schreibrecht an (ohne Rechteprüfung)."""
    with mock_aws():
        verwaltung = {
            "region_name": "us-east-1",
            "aws_access_key_id": "x",
            "aws_secret_access_key": "x",
        }
        boto3.client("s3", **verwaltung).create_bucket(Bucket=BUCKET)
        iam = boto3.client("iam", **verwaltung)
        iam.create_user(UserName="uploader")
        iam.put_user_policy(
            UserName="uploader",
            PolicyName="nur-schreiben",
            PolicyDocument=json.dumps(NUR_SCHREIBEN),
        )
        daten = iam.create_access_key(UserName="uploader")["AccessKey"]
        yield {"id": daten["AccessKeyId"], "geheim": daten["SecretAccessKey"]}


def _pruefe(access_key: str, secret: str, schreibtest: bool = True) -> dict[str, Any]:
    client = erzeuge_client(Verbindung(ENDPUNKT, BUCKET, access_key, secret), max_versuche=1)
    ergebnisse = teste_verbindung(client, BUCKET, "upload/", schreibtest)
    return {p.name: p for p in ergebnisse}


@set_initial_no_auth_action_count(0)
def test_unbekannter_access_key(schluessel: dict[str, str]) -> None:
    ergebnis = _pruefe("AKIAUNBEKANNT0000000", schluessel["geheim"])
    assert ergebnis["Access Key"].stufe is Stufe.FEHLER


@set_initial_no_auth_action_count(0)
def test_falsches_passwort(schluessel: dict[str, str]) -> None:
    ergebnis = _pruefe(schluessel["id"], schluessel["geheim"] + "x")
    assert ergebnis["Passwort (Secret Key)"].stufe is Stufe.FEHLER


@set_initial_no_auth_action_count(0)
def test_nur_schreibrecht_wird_richtig_eingeordnet(schluessel: dict[str, str]) -> None:
    ergebnis = _pruefe(schluessel["id"], schluessel["geheim"])
    assert ergebnis["Zugangsdaten"].stufe is Stufe.OK
    assert ergebnis["Leserecht im Präfix"].stufe is Stufe.HINWEIS
    assert ergebnis["Schreibrecht"].stufe is Stufe.OK
    assert ergebnis["Löschrecht"].stufe is Stufe.HINWEIS
