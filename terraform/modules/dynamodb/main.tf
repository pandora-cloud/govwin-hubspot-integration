variable "name_prefix" {
  type = string
}

resource "aws_dynamodb_table" "sync_state" {
  name         = "${var.name_prefix}-sync-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "entity_mappings" {
  name         = "${var.name_prefix}-entity-mappings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

output "sync_state_table_name" {
  value = aws_dynamodb_table.sync_state.name
}

output "sync_state_table_arn" {
  value = aws_dynamodb_table.sync_state.arn
}

output "entity_mappings_table_name" {
  value = aws_dynamodb_table.entity_mappings.name
}

output "entity_mappings_table_arn" {
  value = aws_dynamodb_table.entity_mappings.arn
}
