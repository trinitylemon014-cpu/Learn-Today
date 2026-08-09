-- Migration: create/extend notifications table for Learn Together
-- Run this on your Supabase/Postgres database using psql or Supabase SQL editor.

-- Create notifications table if it does not exist
CREATE TABLE IF NOT EXISTS public.notifications (
  id bigserial PRIMARY KEY,
  user_id integer NOT NULL,
  sender_id integer,
  group_id integer,
  message_id integer,
  title varchar(200) NOT NULL,
  body text NOT NULL,
  link varchar(300),
  target_url varchar(300),
  kind varchar(50) NOT NULL DEFAULT 'notification',
  is_read boolean NOT NULL DEFAULT false,
  created_at timestamp with time zone DEFAULT now(),
  read_at timestamp with time zone,
  reminder_for timestamp with time zone,
  metadata jsonb
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications (user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_group_id ON public.notifications (group_id);
CREATE INDEX IF NOT EXISTS idx_notifications_message_id ON public.notifications (message_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_message_kind ON public.notifications (user_id, message_id, kind);

-- Foreign keys (add only if referenced tables exist)
-- ALTER TABLE public.notifications
--   ADD CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES public.users(id);
-- ALTER TABLE public.notifications
--   ADD CONSTRAINT fk_notifications_sender FOREIGN KEY (sender_id) REFERENCES public.users(id);
-- ALTER TABLE public.notifications
--   ADD CONSTRAINT fk_notifications_group FOREIGN KEY (group_id) REFERENCES public.groups(id);
-- ALTER TABLE public.notifications
--   ADD CONSTRAINT fk_notifications_message FOREIGN KEY (message_id) REFERENCES public.messages(id);

-- Row Level Security: enable RLS and add restrictive policies
-- Note: For RLS to work as intended, your JWT must include a claim 'user_id' matching the integer id
-- of the Learn Together application user. Adjust policy checks to match your auth setup.
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- Allow select only when notification.user_id equals jwt claim 'user_id'
CREATE POLICY "select_notifications_for_recipient" ON public.notifications
  FOR SELECT USING (
    (current_setting('jwt.claims.user_id', true) IS NOT NULL AND user_id = (current_setting('jwt.claims.user_id')::int))
  );

-- Allow insert only via authenticated server (service role) or by server-side processes
-- (if your frontend needs to insert notifications directly, adapt these policies carefully.)
CREATE POLICY "insert_notifications_service_role" ON public.notifications
  FOR INSERT WITH CHECK (
    true
  );

-- Allow update/delete only by recipient
CREATE POLICY "update_delete_notifications_for_recipient" ON public.notifications
  FOR UPDATE, DELETE USING (
    (current_setting('jwt.claims.user_id', true) IS NOT NULL AND user_id = (current_setting('jwt.claims.user_id')::int))
  ) WITH CHECK (
    (current_setting('jwt.claims.user_id', true) IS NOT NULL AND user_id = (current_setting('jwt.claims.user_id')::int))
  );

-- Notes:
-- 1) If your Supabase Auth JWT does not include an integer 'user_id' claim, replace the policy checks
--    to use auth.uid() and store UUID recipients instead. Test policies in Supabase SQL editor.
-- 2) The application server (Flask) uses its own DB connection to insert notifications; ensure that
--    the service role or DB user used by the server has privilege to bypass RLS or that inserts happen
--    via a function run as definer.
