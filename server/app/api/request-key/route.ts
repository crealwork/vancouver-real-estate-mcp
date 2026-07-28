import { Resend } from "resend";

import { emailFingerprint, issueKey } from "@/lib/auth";

export const runtime = "nodejs";

const EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]+$/;

export async function POST(req: Request) {
  let email: string;
  try {
    const body = await req.json();
    email = String(body.email ?? "").trim();
  } catch {
    return json({ error: "expected JSON body with an email field" }, 400);
  }

  if (!EMAIL_RE.test(email)) {
    return json({ error: "that does not look like an email address" }, 400);
  }

  let key: string;
  try {
    key = issueKey(email);
  } catch {
    return json({ error: "server is missing API_KEY_SECRET" }, 500);
  }

  const host = process.env.PUBLIC_HOST ?? "proof.getsundayable.com/vanre";
  const endpoint = `https://${host}/mcp`;
  const apiKey = process.env.RESEND_API_KEY;

  if (apiKey) {
    try {
      const resend = new Resend(apiKey);
      await resend.emails.send({
        from: process.env.MAIL_FROM ?? "Vancouver RE MCP <noreply@getsundayable.com>",
        to: email,
        subject: "Your Vancouver real estate MCP key",
        text: [
          "Here is your free API key:",
          "",
          key,
          "",
          "Add the server to Claude Code:",
          `  claude mcp add --transport http vanre ${endpoint} \\`,
          `    --header "Authorization: Bearer ${key}"`,
          "",
          "Or in any MCP client config:",
          JSON.stringify(
            {
              mcpServers: {
                vanre: {
                  type: "http",
                  url: endpoint,
                  headers: { Authorization: `Bearer ${key}` },
                },
              },
            },
            null,
            2,
          ),
          "",
          "The data covers Metro Vancouver and the Fraser Valley from 1991 to now.",
          "Ask your agent to call data_coverage first if you want the details.",
        ].join("\n"),
      });
    } catch {
      // Still hand the key back below — a mail failure should not cost the user their key.
      return json({ key, endpoint, warning: "could not send the email; copy the key now" });
    }
    if (process.env.NOTIFY_EMAIL) {
      try {
        const resend = new Resend(apiKey);
        await resend.emails.send({
          from: process.env.MAIL_FROM ?? "Vancouver RE MCP <noreply@getsundayable.com>",
          to: process.env.NOTIFY_EMAIL,
          subject: `New MCP key issued: ${email}`,
          text: `${email}\nfingerprint ${emailFingerprint(email)}\n${new Date().toISOString()}`,
        });
      } catch {
        // Notification is best-effort.
      }
    }
    return json({ ok: true, endpoint, sent_to: email });
  }

  return json({ key, endpoint, note: "mail is not configured; here is the key directly" });
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
