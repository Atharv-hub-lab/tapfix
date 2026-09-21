# TapFix — Smart Guided Troubleshooting Engine

TapFix is a REST API for the **Samsung PRISM GenAI Hackathon 2026-27 — Theme 02: Smart Guided Troubleshooting Engine**.

It converts a vague device complaint into a structured, ordered troubleshooting plan and safely maps supported actions to Samsung Settings deeplinks.

## What TapFix Does

A user can provide a complaint such as:

> My phone display is completely black

TapFix processes the request through a multi-stage pipeline:

```text
User Complaint
      ↓
Query Understanding
      ↓
BM25 Retrieval
      ↓
SIIS Evidence Retrieval
      ↓
Two-Stage LLM Reasoning
      ↓
Trusted Catalog Mapping
      ↓
Schema Validation
      ↓
Fast-Path Cache
      ↓
Structured JSON Response