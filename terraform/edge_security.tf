# Note: This is an example of what would be in the Cloudflare Terraform provider
# or applied via Wrangler/Cloudflare Dashboard.

resource "cloudflare_filter" "rate_limit_filter" {
  zone_id     = var.cloudflare_zone_id
  expression  = "(http.request.uri.path matches \"^/webhook/.*\")"
  description = "Filter for webhook rate limiting"
}

resource "cloudflare_rate_limit" "webhook_limit" {
  zone_id = var.cloudflare_zone_id
  threshold = 100
  period    = 60
  action {
    mode = "simulate" # Start with simulate to avoid false positives
  }
  match {
    request {
      url_pattern = "api.blitz-obs.com/webhook/*"
      methods     = ["POST"]
    }
  }
}
