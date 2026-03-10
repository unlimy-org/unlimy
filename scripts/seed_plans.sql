-- Optional: seed default plans (name, duration_days, price_usd, device_limit)
-- Bot can also create plans on the fly via get_or_create_plan().

INSERT INTO plans(name, duration_days, price_usd, device_limit) VALUES
  ('entry', 30, 3.00, 1),
  ('entry', 90, 8.00, 1),
  ('entry', 360, 25.00, 1),
  ('standard', 30, 5.99, 3),
  ('standard', 90, 15.99, 3),
  ('standard', 360, 59.99, 3),
  ('premium', 30, 8.99, 5),
  ('premium', 90, 23.99, 5),
  ('premium', 360, 89.99, 5),
  ('family', 30, 12.99, 10),
  ('family', 360, 119.99, 10),
  ('business_start', 30, 29.99, 5)
ON CONFLICT (name, duration_days) DO NOTHING;
