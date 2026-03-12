const Dashboard = {
    history: [],
    currentJobId: null,
    pollInterval: null,
    eventSource: null,
    pagesCompleted: 0,

    async init() {
        this.loadHistory();
        this.bindEvents();

        this.history.forEach(job => {
            if (job.status === 'pending' || job.status === 'running') {
                this.streamJob(job.id);
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

            this.history.unshift({
                id: data.job_id,
                url: url,
                status: 'pending',
                submitted_at: Date.now() / 1000
            });

            this.saveHistory();
            this.streamJob(data.job_id);

        } catch (err) {
            alert(`Failed to start job: ${err.message}`);
            UI.showState('idle');
        } finally {
            UI.elements.runBtn.disabled = false;
        }
    },

    _closeStream() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    },

    streamJob(jobId) {
        this._closeStream();
        this.pagesCompleted = 0;

        UI.setLoadingStatus('running', 'Connecting to live stream...', jobId);

        const idx = this.history.findIndex(j => j.id === jobId);
        if (idx !== -1) {
            this.history[idx].status = 'running';
            this.saveHistory();
        }

        try {
            const es = new EventSource(`/api/jobs/${jobId}/stream`);
            this.eventSource = es;

            es.onmessage = async (e) => {
                try {
                    const data = JSON.parse(e.data);

                    if (data.event === 'page_completed') {
                        this.pagesCompleted++;
                        if (jobId === this.currentJobId) {
                            UI.setLoadingStatus('running',
                                `Analyzed ${this.pagesCompleted} page(s) — latest: ${data.url || ''}`,
                                jobId);
                        }
                    }

                    if (data.event === 'job_done') {
                        es.close();
                        this.eventSource = null;
                        const freshIdx = this.history.findIndex(j => j.id === jobId);
                        if (freshIdx !== -1) {
                            this.history[freshIdx].status = data.status;
                            this.saveHistory();
                        }
                        if (jobId === this.currentJobId) {
                            const job = await API.getStatus(jobId);
                            if (data.status === 'success') {
                                UI.renderReport(job);
                            } else {
                                UI.setLoadingStatus('failed', job.error || data.error || 'Job failed', jobId);
                            }
                        }
                    }
                } catch (err) {
                    console.warn('SSE parse error', err);
                }
            };

            es.onerror = () => {
                es.close();
                this.eventSource = null;
                console.warn('SSE connection lost, falling back to polling');
                this.pollJob(jobId);
            };
        } catch {
            this.pollJob(jobId);
        }
    },

    async pollJob(jobId) {
        if (this.pollInterval) clearInterval(this.pollInterval);

        const poll = async () => {
            try {
                const job = await API.getStatus(jobId);

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
                }
            } catch (err) {
                console.error('Poll failed', err);
            }
        };

        poll();
        this.pollInterval = setInterval(poll, 5000);
    },

    async loadJob(jobId) {
        this._closeStream();
        this.currentJobId = jobId;
        UI.renderHistory(this.history, jobId);

        try {
            UI.setLoadingStatus('fetching', 'Retrieving job data...', jobId);
            const job = await API.getStatus(jobId);

            if (job.status === 'success') {
                UI.renderReport(job);
            } else if (job.status === 'failed') {
                UI.setLoadingStatus('failed', job.error, jobId);
            } else {
                this.streamJob(jobId);
            }
        } catch (err) {
            UI.setLoadingStatus('error', err.message, jobId);
        }
    }
};

window.loadJob = (jobId) => Dashboard.loadJob(jobId);

document.addEventListener('DOMContentLoaded', () => Dashboard.init());
