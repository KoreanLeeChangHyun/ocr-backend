#!/usr/bin/env python3

from aws_cdk import App
from ocr_backend.ocr_stack import OcrBackendStack

app = App()
OcrBackendStack(app, "OcrBackendStack")
app.synth()
