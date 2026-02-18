const Dashboard = {
    history: [],
    currentJobId: null,
    pollInterval: null,

    async init() {
        this.loadHistory();
        this.bindEvents();

        // Initial check for active jobs in history
        this.history.forEach(job => {
            if (job.status === 'pending' || job.status === 'running') {
                this.pollJob(job.id);
            }
        });

        UI.renderHistory(this.history, this.currentJobId);
    },

    bindEvents() {
        document.getElementById('run-btn').addEventListener('click', () => this.startNewJob());
        document.getElementById('url-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.startNewJob();
        });
    },

    loadHistory() {
        const saved = localStorage.getItem('qa_history');
        if (saved) {
            try {
                this.history = JSON.parse(saved);
            } catch (e) {
                console.error('Failed to parse history', e);
                this.history = [];
            }
        }
    },

    saveHistory() {
        localStorage.setItem('qa_history', JSON.stringify(this.history));
        UI.renderHistory(this.history, this.currentJobId);
    },

    async startNewJob() {
        const url = UI.elements.urlInput.value.trim();
        if (!url) return alert('Please enter a URL');

        const options = {
            maxPages: parseInt(document.getElementById('max-pages').value) || null,
            maxDepth: parseInt(document.getElementById('max-depth').value) || 0,
            runAi: document.getElementById('run-ai').checked
        };

        try {
            UI.elements.runBtn.disabled = true;
            UI.setLoadingStatus('pending', 'Queueing your request...', null);

            const data = await API.runQA(url, options);
            this.currentJobId = data.job_id;

            // Add to history
            this.history.unshift({
                id: data.job_id,
                url: url,
                status: 'pending',
                submitted_at: Date.now() / 1000
            });

            this.saveHistory();
            this.pollJob(data.job_id);

        } catch (err) {
            alert(`Failed to start job: ${err.message}`);
            UI.showState('idle');
        } finally {
            UI.elements.runBtn.disabled = false;
        }
    },

    async pollJob(jobId) {
        if (this.pollInterval) clearInterval(this.pollInterval);

        const poll = async () => {
            try {
                const job = await API.getStatus(jobId);

                // Update history item
                const idx = this.history.findIndex(j => j.id === jobId);
                if (idx !== -1) {
                    this.history[idx].status = job.status;
                    this.saveHistory();
                }

                if (jobId === this.currentJobId) {
                    if (job.status === 'success') {
                        clearInterval(this.pollInterval);
                        UI.renderReport(job);
                    } else if (job.status === 'failed') {
                        clearInterval(this.pollInterval);
                        UI.setLoadingStatus('failed', job.error || 'Job failed unexpectedly', jobId);
                    } else {
                        UI.setLoadingStatus(job.status, `Updating status: ${job.status}...`, jobId);
                    }
                } else if (['success', 'failed'].includes(job.status)) {
                    // Stop polling if we aren't looking at this job anymore but it finished
                    // (Actually we might want to keep history polling broadly, but for now simple)
                }

            } catch (err) {
                console.error('Poll failed', err);
            }
        };

        poll();
        this.pollInterval = setInterval(poll, 5000);
    },

    async loadJob(jobId) {
        this.currentJobId = jobId;
        UI.renderHistory(this.history, jobId);

        try {
            UI.setLoadingStatus('fetching', 'Retrieving job data...', jobId);
            const job = await API.getStatus(jobId);

            if (job.status === 'success') {
                if (this.pollInterval) clearInterval(this.pollInterval);
                UI.renderReport(job);
            } else if (job.status === 'failed') {
                if (this.pollInterval) clearInterval(this.pollInterval);
                UI.setLoadingStatus('failed', job.error, jobId);
            } else {
                this.pollJob(jobId);
            }
        } catch (err) {
            UI.setLoadingStatus('error', err.message, jobId);
        }
    }
};

// Global entry point for history clicks
window.loadJob = (jobId) => Dashboard.loadJob(jobId);

document.addEventListener('DOMContentLoaded', () => Dashboard.init());
