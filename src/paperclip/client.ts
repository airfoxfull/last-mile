// Paperclip API client
const PAPERCLIP_URL = process.env.PAPERCLIP_URL ?? "http://localhost:3100";

async function paperclipRequest(path: string, options?: RequestInit) {
  const res = await fetch(`${PAPERCLIP_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`Paperclip ${res.status}: ${await res.text()}`);
  return res.json();
}

export const paperclip = {
  // Wake an agent and wait for it to finish
  async invokeAgent(agentId: string, issueId: string, reason: string) {
    return paperclipRequest(`/api/agents/${agentId}/wakeup`, {
      method: "POST",
      body: JSON.stringify({ source: "on_demand", issueId, reason }),
    });
  },

  // Create an issue
  async createIssue(companyId: string, data: Record<string, unknown>) {
    return paperclipRequest(`/api/companies/${companyId}/issues`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  // Write a document to an issue
  async writeDocument(issueId: string, key: string, title: string, body: string) {
    return paperclipRequest(`/api/issues/${issueId}/documents/${key}`, {
      method: "PUT",
      body: JSON.stringify({ title, format: "markdown", body }),
    });
  },

  // Read a document from an issue
  async readDocument(issueId: string, key: string) {
    return paperclipRequest(`/api/issues/${issueId}/documents/${key}`);
  },

  // Get issue details
  async getIssue(issueId: string) {
    return paperclipRequest(`/api/issues/${issueId}`);
  },

  // Update issue status
  async updateIssue(issueId: string, patch: Record<string, unknown>) {
    return paperclipRequest(`/api/issues/${issueId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },

  // Add comment to issue
  async addComment(issueId: string, body: string) {
    return paperclipRequest(`/api/issues/${issueId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  },

  // Get agent status (for polling completion)
  async getAgent(agentId: string) {
    return paperclipRequest(`/api/agents/${agentId}`);
  },
};
