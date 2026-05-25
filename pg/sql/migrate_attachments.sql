-- Migration: add attachments JSONB column to areas and equipment_groups
-- Run this against an existing database that was created before these columns existed.

ALTER TABLE areas
    ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]';

ALTER TABLE equipment_groups
    ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]';
