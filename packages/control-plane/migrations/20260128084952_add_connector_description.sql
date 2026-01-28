-- Migration: add_connector_description
-- Description: Add description field to connectors table for widget display
-- Safe: Yes (additive, nullable column)
-- Rollback: ALTER TABLE connectors DROP COLUMN description;

ALTER TABLE connectors ADD COLUMN description TEXT;
