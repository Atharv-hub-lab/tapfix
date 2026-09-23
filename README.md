# TapFix — Smart Guided Troubleshooting Engine

TapFix is a REST API built for the **Samsung PRISM GenAI Hackathon 2026-27 — Theme 02: Smart Guided Troubleshooting Engine**.

It converts a vague device complaint into a structured troubleshooting plan and safely maps supported actions to Samsung Settings deeplinks.

---

## Problem

Users often describe device problems in vague language such as:

> My phone display is completely black.

A troubleshooting system needs to understand the complaint, identify the relevant technical issue, select appropriate troubleshooting actions, and guide the user directly toward the required Settings screen.

TapFix is designed to automate this process while keeping the final troubleshooting actions grounded in the provided SIIS evidence and Samsung deeplink catalog.

---

## What TapFix Does

A typical request follows this pipeline:

```text
User Complaint
      ↓
Query Understanding
      ↓
Query Normalization
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