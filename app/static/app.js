const roleSelect = document.querySelector("#role-select");
const taskSelect = document.querySelector("#task-select");
const sessionStatus = document.querySelector("#session-status");
const softwareHistory = document.querySelector("#software-history");
const generateGuideButton = document.querySelector("#generate-guide");
const guideContent = document.querySelector("#guide-content");
const chatForm = document.querySelector("#chat-form");
const chatMessage = document.querySelector("#chat-message");
const chatContent = document.querySelector("#chat-content");
const proposeUpdateButton = document.querySelector("#propose-update");
const proposalContent = document.querySelector("#proposal-content");
const approvalForm = document.querySelector("#approval-form");
const adminSecret = document.querySelector("#admin-secret");
const updateStatus = document.querySelector("#update-status");

let roles = [];
let sessionReady = false;
let currentProposal = null;

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      sessionReady = false;
      updateControls();
    }
    throw new Error(payload.detail || `Request failed (${response.status}).`);
  }
  return payload;
}

function updateControls() {
  generateGuideButton.disabled = !sessionReady;
  chatMessage.disabled = !sessionReady;
  chatForm.querySelector("button").disabled = !sessionReady;
  proposeUpdateButton.disabled = !sessionReady || currentProposal !== null;
  roleSelect.disabled = sessionReady;
}

function renderSources(parent, sources) {
  if (!sources.length) return;
  const heading = document.createElement("h4");
  heading.textContent = "Sources";
  parent.append(heading);
  const list = document.createElement("ul");
  list.className = "sources";
  for (const source of sources) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${source.title} — ${source.publisher} (${source.version})`;
    item.append(link);
    list.append(item);
  }
  parent.append(list);
}

function showUnsupported(parent, unsupported) {
  if (!unsupported) return;
  const note = document.createElement("p");
  note.className = "notice";
  note.textContent = "The curated demo material does not support a reliable answer for this request.";
  parent.prepend(note);
}

function populateTasks(roleId, selectedTaskId = null) {
  const role = roles.find((item) => item.id === roleId);
  taskSelect.replaceChildren();
  for (const task of role?.tasks || []) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = task.name;
    taskSelect.append(option);
  }
  if (selectedTaskId && [...taskSelect.options].some((option) => option.value === selectedTaskId)) {
    taskSelect.value = selectedTaskId;
  }
}

function renderGuide(guide) {
  guideContent.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = guide.title;
  const introduction = document.createElement("p");
  introduction.textContent = guide.introduction;
  guideContent.append(heading, introduction);
  showUnsupported(guideContent, guide.unsupported);
  if (guide.steps.length) {
    const list = document.createElement("ol");
    for (const step of guide.steps) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${step.title}: `;
      const instructions = document.createElement("span");
      instructions.textContent = step.instructions;
      item.append(title, instructions);
      list.append(item);
    }
    guideContent.append(list);
  }
  renderSources(guideContent, guide.sources);
}

function addChatMessage(label, text, sources = [], unsupported = false) {
  const article = document.createElement("article");
  const heading = document.createElement("strong");
  heading.textContent = label;
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  article.append(heading, paragraph);
  showUnsupported(article, unsupported);
  renderSources(article, sources);
  chatContent.prepend(article);
}

function renderProposal(proposal) {
  currentProposal = proposal;
  proposalContent.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = `${proposal.package}: ${proposal.current_version} → ${proposal.proposed_version}`;
  const explanation = document.createElement("p");
  explanation.textContent = proposal.explanation;
  const status = document.createElement("p");
  status.textContent = `Status: ${proposal.status}`;
  proposalContent.append(heading, explanation, status);
  updateStatus.textContent = proposal.message || "";
  approvalForm.hidden = proposal.status !== "pending";
  updateControls();
}

function renderSoftwareHistory(history) {
  softwareHistory.replaceChildren();
  if (!history || !history.length) return;
  const heading = document.createElement("h4");
  heading.textContent = "Software background on record";
  softwareHistory.append(heading);
  const list = document.createElement("ul");
  list.className = "sources";
  for (const software of history) {
    const item = document.createElement("li");
    item.textContent =
      `${software.name} (${software.vendor}) — ${software.category}, ` +
      `${software.years_used} yr, ${software.proficiency}`;
    list.append(item);
  }
  softwareHistory.append(list);
}

async function restoreSession() {
  try {
    const session = await apiRequest("/api/session");
    roleSelect.value = session.role.id;
    populateTasks(session.role.id, session.context.active_task_id);
    sessionReady = true;
    sessionStatus.textContent = `Session active for ${session.role.name}.`;
    updateControls();
    renderSoftwareHistory(session.software_history);
    if (session.context.pending_update) renderProposal(session.context.pending_update);
  } catch (error) {
    sessionStatus.textContent = "Choose a role and start a temporary demo session.";
  }
}

async function loadRoles() {
  roles = await apiRequest("/api/roles");
  roleSelect.replaceChildren();
  for (const role of roles) {
    const option = document.createElement("option");
    option.value = role.id;
    option.textContent = role.name;
    roleSelect.append(option);
  }
  populateTasks(roleSelect.value);
  sessionStatus.textContent = "Choose a role and start a temporary demo session.";
  updateControls();
  await restoreSession();
}

roleSelect.addEventListener("change", () => {
  populateTasks(roleSelect.value);
  softwareHistory.replaceChildren();
});

document.querySelector("#start-session").addEventListener("click", async () => {
  try {
    const session = await apiRequest("/api/session", {
      method: "POST",
      body: JSON.stringify({ role_id: roleSelect.value }),
    });
    sessionReady = true;
    currentProposal = null;
    proposalContent.replaceChildren();
    approvalForm.hidden = true;
    updateStatus.textContent = "";
    sessionStatus.textContent = `Session active for ${session.role.name}.`;
    updateControls();
    renderSoftwareHistory(session.software_history);
  } catch (error) {
    sessionStatus.textContent = error.message;
  }
});

generateGuideButton.addEventListener("click", async () => {
  guideContent.textContent = "Generating a cited guide…";
  try {
    const guide = await apiRequest("/api/guide", {
      method: "POST",
      body: JSON.stringify({ task_id: taskSelect.value }),
    });
    renderGuide(guide);
  } catch (error) {
    guideContent.textContent = error.message;
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatMessage.value.trim();
  if (!message) return;
  chatMessage.value = "";
  addChatMessage("You", message);
  try {
    const answer = await apiRequest("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    addChatMessage("Assistant", answer.answer, answer.sources, answer.unsupported);
  } catch (error) {
    addChatMessage("Assistant", error.message);
  }
});

proposeUpdateButton.addEventListener("click", async () => {
  updateStatus.textContent = "Creating the fixed demo proposal…";
  try {
    const proposal = await apiRequest("/api/updates/proposals", { method: "POST" });
    renderProposal(proposal);
  } catch (error) {
    updateStatus.textContent = error.message;
  }
});

approvalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentProposal) return;
  const secret = adminSecret.value;
  adminSecret.value = "";
  updateStatus.textContent = "Submitting administrator approval…";
  try {
    const result = await apiRequest(`/api/updates/${encodeURIComponent(currentProposal.id)}/approve`, {
      method: "POST",
      headers: { "X-Demo-Admin-Secret": secret },
    });
    renderProposal(result);
  } catch (error) {
    updateStatus.textContent = error.message;
  }
});

loadRoles().catch((error) => {
  sessionStatus.textContent = error.message;
});