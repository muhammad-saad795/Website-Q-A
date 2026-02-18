const UI = {
    elements: {
        idle: document.getElementById('idle-state'),
        loading: document.getElementById('loading-state'),
        result: document.getElementById('result-state'),
        statusAnimation: document.getElementById('status-animation'),
        statusText: document.getElementById('status-text'),
        statusDetail: document.getElementById('status-detail'),
        jobIdDisplay: document.getElementById('job-id-display'),
        history: document.getElementById('job-history'),
        reports: document.getElementById('reports-container'),
        masterSummary: document.getElementById('master-summary-container'),
        urlInput: document.getElementById('url-input'),
        runBtn: document.getElementById('run-btn')
    },

    showState(state) {
        this.elements.idle.style.display = state === 'idle' ? 'block' : 'none';
        this.elements.loading.style.display = state === 'loading' ? 'block' : 'none';
        this.elements.result.style.display = state === 'result' ? 'block' : 'none';
    },

    setLoadingStatus(status, detail, jobId) {
        this.showState('loading');
        this.elements.statusText.innerText = status.charAt(0).toUpperCase() + status.slice(1);
        this.elements.statusDetail.innerText = detail || '';
        this.elements.jobIdDisplay.innerText = jobId ? `Job ID: ${jobId}` : '';

        // Update animation
        let animationHtml = '';
        if (status === 'pending') {
            animationHtml = `
                <div class="stack-animation">
                    <div class="stack-item"></div>
                    <div class="stack-item"></div>
                    <div class="stack-item"></div>
                </div>
            `;
        } else if (status === 'running') {
            animationHtml = `
                <div class="scan-container">
                    <div class="scan-line"></div>
                </div>
            `;
        }
        this.elements.statusAnimation.innerHTML = animationHtml;
    },

    renderHistory(jobs, activeJobId) {
        if (!jobs || jobs.length === 0) {
            this.elements.history.innerHTML = '<div class="empty-state">No past jobs</div>';
            return;
        }

        this.elements.history.innerHTML = jobs.map(job => `
            <div class="history-item ${job.id === activeJobId ? 'active' : ''}" onclick="window.loadJob('${job.id}')">
                <div class="url">${job.url}</div>
                <div class="meta">${new Date(job.submitted_at * 1000).toLocaleString()}</div>
                <div class="meta" style="font-weight:bold; color:var(--status-${job.status})">${job.status}</div>
            </div>
        `).join('');
    },

    renderReport(job) {
        this.showState('result');
        const res = job.result;

        // Master AI Summary
        if (res.master_qa_audit && res.master_qa_audit !== "Skipped: AI analysis disabled.") {
            this.elements.masterSummary.innerHTML = `
                <div class="card ai-summary-card">
                    <h3 style="margin-bottom:12px; display:flex; align-items:center; gap:8px;">
                        <i data-lucide="sparkles"></i> AI Master Audit
                    </h3>
                    <div style="line-height:1.6; color:var(--text-primary); font-size:0.95rem;">
                        ${this._parseSimpleMarkdown(res.master_qa_audit)}
                    </div>
                </div>
            `;
        } else {
            this.elements.masterSummary.innerHTML = '';
        }

        // Individual Reports
        const allReports = [
            ...(res.internal_reports || []).map(r => ({ ...r, type: 'Internal' })),
            ...(res.external_reports || []).map(r => ({ ...r, type: 'External' }))
        ];

        this.elements.reports.innerHTML = allReports.map(report => this._renderReportCard(report)).join('');

        // Re-trigger icons
        if (window.lucide) window.lucide.createIcons();
    },

    _renderReportCard(report) {
        const urlReport = report.url_report || {};
        const perf = urlReport.performance || {};
        const isInternal = report.type === 'Internal';

        const statusClass = urlReport.http_status < 400 ? 'healthy' : 'error';
        const statusLabel = urlReport.status_label || (urlReport.http_status ? `HTTP ${urlReport.http_status}` : 'Unknown');

        return `
            <div class="card">
                <div class="card-header">
                    <div style="font-size:0.75rem; color:var(--accent-blue); font-weight:bold; margin-bottom:4px;">${report.type.toUpperCase()} PAGE</div>
                    <span class="status-badge badge-${statusClass}">${statusLabel}</span>
                </div>
                <div class="url" style="font-weight:600; font-size:0.9rem; word-break:break-all; margin-bottom:12px;">${report.url}</div>
                
                <div class="performance-grid">
                    <div class="perf-item">
                        <div class="perf-label">Load Time</div>
                        <div class="perf-value">${perf.total_load_seconds?.toFixed(2) || '--'}s</div>
                    </div>
                    <div class="perf-item">
                        <div class="perf-label">Nav Time</div>
                        <div class="perf-value">${perf.navigation_seconds?.toFixed(2) || '--'}s</div>
                    </div>
                </div>

                ${isInternal && report.agent_summary ? `
                    <div style="margin-top:16px; padding-top:16px; border-top:1px solid var(--glass-border);">
                        <div class="perf-label" style="margin-bottom:8px;">AI Page Summary</div>
                        <div style="font-size:0.85rem; color:var(--text-secondary); line-height:1.5;">
                            ${report.agent_summary}
                        </div>
                    </div>
                ` : ''}

                ${urlReport.console_logs?.length > 0 ? `
                    <div class="console-toggle" onclick="UI.toggleConsole(this)">
                         <i data-lucide="terminal" style="width:14px; height:14px;"></i>
                         <span>${urlReport.console_logs.length} Console Errors Detected</span>
                         <i data-lucide="chevron-down" style="width:14px; height:14px; margin-left:auto;"></i>
                    </div>
                    <div class="console-logs-container" style="display:none;">
                        ${urlReport.console_logs.map(log => `
                            <div class="console-entry ${log.type || 'info'}">
                                <span style="opacity:0.5; margin-right:8px;">[${log.type?.toUpperCase() || 'INFO'}]</span>
                                <span>${this._escapeHtml(log.text)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    },

    toggleConsole(element) {
        const container = element.nextElementSibling;
        const icon = element.querySelector('[data-lucide="chevron-down"], [data-lucide="chevron-up"]');

        if (container.style.display === 'none') {
            container.style.display = 'block';
            element.querySelector('.lucide-chevron-down')?.setAttribute('data-lucide', 'chevron-up');
        } else {
            container.style.display = 'none';
            element.querySelector('.lucide-chevron-up')?.setAttribute('data-lucide', 'chevron-down');
        }

        if (window.lucide) window.lucide.createIcons();
    },

    _escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    },

    _parseSimpleMarkdown(text) {
        if (!text) return '';
        return text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br>');
    }
};
