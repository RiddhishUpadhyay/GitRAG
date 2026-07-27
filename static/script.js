document.addEventListener("DOMContentLoaded", () => {
    // Auth Elements
    const loginOverlay = document.getElementById("login-overlay");
    const loginForm = document.getElementById("login-form");
    const loginUsername = document.getElementById("login-username");
    const loginPassword = document.getElementById("login-password");
    const confirmPasswordGroup = document.getElementById("confirm-password-group");
    const confirmPasswordInput = document.getElementById("login-confirm-password");
    const submitBtn = document.getElementById("login-submit-btn");
    const loginErrorMsg = document.getElementById("login-error-msg");
    const logoutBtn = document.getElementById("logout-btn");
    
    const authTitle = document.getElementById("auth-title");
    const authToggleText = document.getElementById("auth-toggle-text");
    const authToggleLink = document.getElementById("auth-toggle-link");

    // Main App Elements
    const ingestForm = document.getElementById("ingest-form");
    const repoUrlInput = document.getElementById("repo-url");
    const ingestBtn = document.getElementById("ingest-btn");
    
    const statusPanel = document.getElementById("status-panel");
    const statusTitle = document.getElementById("status-title");
    const statusProgressBar = document.getElementById("status-progress-bar");
    const statusMessage = document.getElementById("status-message");
    
    const reposList = document.getElementById("repos-list");
    const noRepos = document.getElementById("no-repos");
    const activeRepoName = document.getElementById("active-repo-name");
    const resyncBtn = document.getElementById("resync-btn");
    
    const chatMessages = document.getElementById("chat-messages");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    
    let activeRepo = null; // Object {id, url}
    let pollingInterval = null;
    let authMode = "login"; // "login" or "signup"

    // --- Authentication Wrapper ---
    async function authFetch(url, options = {}) {
        const token = sessionStorage.getItem("auth_token");
        options.headers = options.headers || {};
        if (token) {
            options.headers["Authorization"] = "Bearer " + token;
        }
        const response = await fetch(url, options);
        if (response.status === 401) {
            // Token expired or invalid, log out!
            sessionStorage.removeItem("auth_token");
            window.location.reload();
            return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 });
        }
        return response;
    }

    // Check login state on start (sessionStorage is cleared when tab/browser closes)
    const token = sessionStorage.getItem("auth_token");
    if (!token) {
        loginOverlay.classList.remove("hidden");
    } else {
        loginOverlay.classList.add("hidden");
        loadRepositories();
    }

    // Toggle between Login and Sign Up modes
    authToggleLink.addEventListener("click", (e) => {
        e.preventDefault();
        loginErrorMsg.classList.add("hidden");
        
        if (authMode === "login") {
            authMode = "signup";
            authTitle.textContent = "📝 GitRAG Sign Up";
            confirmPasswordGroup.classList.remove("hidden");
            confirmPasswordInput.required = true;
            submitBtn.textContent = "Create Account";
            authToggleText.textContent = "Already have an account?";
            authToggleLink.textContent = "Log In";
        } else {
            authMode = "login";
            authTitle.textContent = "🔑 GitRAG Login";
            confirmPasswordGroup.classList.add("hidden");
            confirmPasswordInput.required = false;
            confirmPasswordInput.value = "";
            submitBtn.textContent = "Unlock Dashboard";
            authToggleText.textContent = "Don't have an account?";
            authToggleLink.textContent = "Sign Up";
        }
    });

    // Login / Sign Up Form Submit
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = loginUsername.value.trim();
        const password = loginPassword.value.trim();
        
        if (authMode === "signup") {
            const confirmPass = confirmPasswordInput.value.trim();
            if (password !== confirmPass) {
                loginErrorMsg.textContent = "Error: Passwords do not match.";
                loginErrorMsg.classList.remove("hidden");
                return;
            }
        }
        
        const endpoint = authMode === "login" ? "/api/login" : "/api/register";
        
        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            });
            
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Authentication failed");
            }
            
            const data = await response.json();
            sessionStorage.setItem("auth_token", data.access_token);
            loginOverlay.classList.add("hidden");
            loginErrorMsg.classList.add("hidden");
            
            // Clear inputs
            loginUsername.value = "";
            loginPassword.value = "";
            confirmPasswordInput.value = "";
            
            loadRepositories();
        } catch (err) {
            loginErrorMsg.textContent = err.message;
            loginErrorMsg.classList.remove("hidden");
        }
    });

    // Logout Click
    logoutBtn.addEventListener("click", async () => {
        try {
            await authFetch("/api/logout", { method: "POST" });
        } catch (e) {
            console.error("Logout API call failed:", e);
        }
        sessionStorage.removeItem("auth_token");
        window.location.reload();
    });

    // Autoresize textarea
    chatInput.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight) + "px";
    });

    // Ingest Repository
    ingestForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const url = repoUrlInput.value.trim();
        if (!url) return;

        ingestBtn.disabled = true;
        ingestBtn.textContent = "...";
        
        try {
            const response = await authFetch("/api/ingest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ repo_url: url })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Failed to trigger ingestion");
            }

            const data = await response.json();
            startPolling(data.job_id, url);
            repoUrlInput.value = "";
        } catch (err) {
            alert("Error: " + err.message);
            ingestBtn.disabled = false;
            ingestBtn.textContent = "Index";
        }
    });

    // Manual Re-sync
    resyncBtn.addEventListener("click", async () => {
        if (!activeRepo) return;
        
        resyncBtn.disabled = true;
        resyncBtn.textContent = "Re-syncing...";
        
        try {
            const response = await authFetch("/api/resync", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ repo_url: activeRepo.url })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Failed to trigger resync");
            }

            const data = await response.json();
            startPolling(data.job_id, activeRepo.url);
        } catch (err) {
            alert("Error during resync: " + err.message);
            resyncBtn.disabled = false;
            resyncBtn.textContent = "🔄 Re-sync";
        }
    });

    // Chat Submission
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const query = chatInput.value.trim();
        if (!query || !activeRepo) return;

        chatInput.value = "";
        chatInput.style.height = "auto";
        
        appendMessage("user", query, []);
        const loadingId = appendLoadingMessage();

        try {
            const response = await authFetch("/api/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    repo_url: activeRepo.url,
                    query: query
                })
            });

            removeLoadingMessage(loadingId);

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Query failed");
            }

            const data = await response.json();
            appendMessage("bot", data.answer, data.citations);
        } catch (err) {
            removeLoadingMessage(loadingId);
            appendMessage("bot", `Failed to get response: ${err.message}. Make sure Qdrant and GROQ_API_KEY are properly configured.`);
        }
    });

    // --- Core Functions ---

    async function loadRepositories() {
        try {
            const response = await authFetch("/api/repos");
            if (!response.ok) throw new Error("Failed to load repositories");
            
            const repos = await response.json();
            reposList.innerHTML = "";

            if (repos.length === 0) {
                noRepos.classList.remove("hidden");
                return;
            }

            noRepos.classList.add("hidden");
            repos.forEach(repo => {
                const li = document.createElement("li");
                li.className = `repo-item ${activeRepo && activeRepo.id === repo.id ? 'active' : ''}`;
                
                const nameParts = repo.url.replace(/\/$/, "").split("/");
                const name = nameParts.slice(-2).join("/");

                li.innerHTML = `
                    <div>
                        <div class="repo-name" title="${name}">${name}</div>
                        <div class="repo-url" title="${repo.url}">${repo.url}</div>
                    </div>
                    <span class="repo-active-check"></span>
                `;
                
                li.addEventListener("click", () => selectRepository(repo));
                reposList.appendChild(li);
            });
        } catch (err) {
            console.error("Error loading repos:", err);
        }
    }

    function selectRepository(repo) {
        activeRepo = repo;
        
        document.querySelectorAll(".repo-item").forEach(item => {
            const nameEl = item.querySelector(".repo-url");
            if (nameEl && nameEl.title === repo.url) {
                item.classList.add("active");
            } else {
                item.classList.remove("active");
            }
        });

        const nameParts = repo.url.replace(/\/$/, "").split("/");
        activeRepoName.textContent = nameParts.slice(-2).join("/");
        resyncBtn.classList.remove("hidden");
        resyncBtn.disabled = false;
        resyncBtn.textContent = "🔄 Re-sync";

        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.placeholder = "Ask a question about this repository...";
        chatInput.focus();

        // Load chat history for this repository from the backend
        renderChatHistory(repo.id);
    }

    async function renderChatHistory(repoId) {
        chatMessages.innerHTML = "";
        const loadingId = appendLoadingMessage("Loading conversation history...");
        
        try {
            const response = await authFetch(`/api/history/${repoId}`);
            removeLoadingMessage(loadingId);
            
            if (!response.ok) throw new Error("Failed to load history");
            
            const history = await response.json();
            if (history.length > 0) {
                history.forEach(msg => {
                    appendMessage(msg.sender, msg.text, msg.citations);
                });
            } else {
                showWelcomeMessage();
            }
        } catch (e) {
            removeLoadingMessage(loadingId);
            console.error("Error loading chat history from backend:", e);
            showWelcomeMessage();
        }
    }

    function showWelcomeMessage() {
        chatMessages.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon">💬</div>
                <h2>Ask Questions About Your Code</h2>
                <p>Enter a GitHub repository URL on the left sidebar to clone, chunk, and embed the repository. Once indexed, select it and start asking technical questions!</p>
                <div class="example-questions">
                    <button class="example-btn">How does the caching layer work?</button>
                    <button class="example-btn">Where is the auth token validated?</button>
                    <button class="example-btn">What are the main API endpoints?</button>
                </div>
            </div>
        `;
        bindExampleButtons();
    }

    function bindExampleButtons() {
        document.querySelectorAll(".example-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                if (!activeRepo) {
                    alert("Please select or index a repository first!");
                    return;
                }
                chatInput.value = e.target.textContent;
                chatInput.focus();
                chatInput.dispatchEvent(new Event("input"));
            });
        });
    }

    function startPolling(jobId, repoUrl) {
        statusPanel.classList.remove("hidden");
        statusTitle.textContent = "Indexing...";
        statusProgressBar.style.width = "5%";
        statusMessage.textContent = "Connecting to queue...";

        if (pollingInterval) clearInterval(pollingInterval);

        pollingInterval = setInterval(async () => {
            try {
                const response = await authFetch(`/api/status/${jobId}`);
                if (!response.ok) throw new Error("Job not found");
                
                const data = await response.json();
                statusMessage.textContent = data.progress || "Indexing repository...";

                if (data.status === "finished" || data.status === "completed") {
                    clearInterval(pollingInterval);
                    statusProgressBar.style.width = "100%";
                    statusTitle.textContent = "Completed!";
                    statusMessage.textContent = "Repository parsed and indexed successfully!";
                    
                    setTimeout(() => {
                        statusPanel.classList.add("hidden");
                        ingestBtn.disabled = false;
                        ingestBtn.textContent = "Index";
                    }, 3000);

                    await loadRepositories();
                    const repoId = jobId.replace("job_", "").replace("local_", "");
                    selectRepository({ id: repoId, url: repoUrl });
                    
                } else if (data.status === "failed") {
                    clearInterval(pollingInterval);
                    statusProgressBar.style.width = "100%";
                    statusProgressBar.style.backgroundColor = "var(--error)";
                    statusTitle.textContent = "Failed";
                    statusMessage.textContent = data.progress || "Indexing failed. Repository might be too large or invalid.";
                    
                    setTimeout(() => {
                        statusPanel.classList.add("hidden");
                        statusProgressBar.style.backgroundColor = "";
                        ingestBtn.disabled = false;
                        ingestBtn.textContent = "Index";
                    }, 5000);
                } else {
                    const progressMap = {
                        "Cloning": 15,
                        "Filtering": 35,
                        "Chunking": 55,
                        "dense": 75,
                        "sparse": 90
                    };
                    
                    let progress = 10;
                    for (const [key, val] of Object.entries(progressMap)) {
                        if (data.progress && data.progress.includes(key)) {
                            progress = val;
                            break;
                        }
                    }
                    statusProgressBar.style.width = `${progress}%`;
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 1500);
    }

    // --- Message Rendering Helpers ---

    function appendMessage(sender, text, citations = []) {
        const messageDiv = document.createElement("div");
        messageDiv.className = `message ${sender}`;
        
        const avatar = document.createElement("div");
        avatar.className = "message-avatar";
        avatar.textContent = sender === "user" ? "U" : "AI";

        const content = document.createElement("div");
        content.className = "message-content";

        let formattedText = escapeHtml(text)
            .replace(/\n\n/g, "</p><p>")
            .replace(/\n/g, "<br>");
            
        formattedText = formattedText.replace(/`([^`]+)`/g, "<code>$1</code>");

        const citationRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
        formattedText = formattedText.replace(citationRegex, (match, linkText, linkUrl) => {
            return `<a href="#${linkUrl}" class="inline-citation" data-path="${linkUrl}">${linkText}</a>`;
        });

        content.innerHTML = `<p>${formattedText}</p>`;

        if (citations && citations.length > 0) {
            const citationsDiv = document.createElement("div");
            citationsDiv.className = "citations-list";
            citationsDiv.innerHTML = `<h4>Citations & Snippets</h4>`;
            
            const grid = document.createElement("div");
            grid.className = "citations-grid";

            citations.forEach(cit => {
                const card = document.createElement("div");
                card.className = "citation-card";
                card.id = `${cit.file_path}#L${cit.start_line}-L${cit.end_line}`;
                card.innerHTML = `
                    <div class="citation-header">
                        <a href="https://github.com/${activeRepo.url.split("github.com/")[1]}/blob/master/${cit.file_path}#L${cit.start_line}-L${cit.end_line}" 
                           target="_blank" class="citation-link">
                           ${cit.file_path} (Lines ${cit.start_line}-${cit.end_line})
                        </a>
                        <span class="citation-badge">Score: ${cit.score.toFixed(2)}</span>
                    </div>
                    <pre class="citation-code"><code>${escapeHtml(cit.content)}</code></pre>
                `;
                grid.appendChild(card);
            });
            
            citationsDiv.appendChild(grid);
            content.appendChild(citationsDiv);
        }

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(content);
        chatMessages.appendChild(messageDiv);
        
        chatMessages.scrollTop = chatMessages.scrollHeight;

        content.querySelectorAll(".inline-citation").forEach(link => {
            link.addEventListener("click", (e) => {
                e.preventDefault();
                const pathId = link.getAttribute("data-path");
                const targetCard = document.getElementById(pathId);
                if (targetCard) {
                    targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
                    targetCard.style.borderColor = "var(--accent)";
                    targetCard.style.boxShadow = "0 0 12px var(--accent-glow)";
                    setTimeout(() => {
                        targetCard.style.borderColor = "";
                        targetCard.style.boxShadow = "";
                    }, 2000);
                }
            });
        });
    }

    function appendLoadingMessage(msg = "Analyzing repository and fetching answer") {
        const id = "loading-" + Date.now();
        const loadingDiv = document.createElement("div");
        loadingDiv.className = "loading-message bot";
        loadingDiv.id = id;
        loadingDiv.innerHTML = `
            <span>${msg}</span>
            <div class="dot-flashing"></div>
        `;
        chatMessages.appendChild(loadingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }

    // Helper to remove loading spinner element
    function removeLoadingMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    // Simple HTML escaping helper to prevent rendering raw HTML tags injected from codebase
    function escapeHtml(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
