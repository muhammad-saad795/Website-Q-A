const API = {
    baseUrl: '/api',

    async runQA(url, options = {}) {
        const response = await fetch(`${this.baseUrl}/run-qa`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                max_pages: options.maxPages || null,
                max_depth: options.maxDepth || null,
                run_ai: options.runAi ?? true
            })
        });
        return this._handleResponse(response);
    },

    async getStatus(jobId) {
        const response = await fetch(`${this.baseUrl}/status/${jobId}`);
        return this._handleResponse(response);
    },

    async listJobs(limit = 20) {
        const response = await fetch(`${this.baseUrl}/jobs?limit=${limit}`);
        return this._handleResponse(response);
    },

    async _handleResponse(response) {
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(data.error?.message || 'API request failed');
            error.code = data.error?.code;
            throw error;
        }
        return data;
    }
};
