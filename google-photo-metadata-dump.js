(async function () {
    window.allSnapshots = [];
    const POLL_INTERVAL = 50;
    const MAX_TIMEOUT = 5000;
    const STABILITY_RUN_REQUIRED = 5;
    let hasJiggledForCurrentTransition = false;

    const showToast = (msg, duration = 2000) => {
        let container = document.getElementById('gp-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'gp-toast-container';
            container.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.textContent = msg;
        toast.style.cssText = 'background:rgba(32,33,36,0.9);color:#fff;padding:12px 20px;border-radius:8px;font-family:Roboto,Arial,sans-serif;font-size:14px;box-shadow:0 4px 6px rgba(0,0,0,0.3);transition:opacity 0.3s ease;';
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    };

    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth) &&
            el.offsetWidth > 0 &&
            el.offsetHeight > 0
        );
    };

    const isBlacklisted = (k) => {
        const forbiddenExact = [
            "Close info", "Keyboard shortcuts", "Edit faces",
            "Learn more about backup quality", "Edit location", "Map Data",
            "Map Scale", "Terms (opens in new tab)", "Terms",
            "Map data", "Map scale", "Learn more"
        ];
        return forbiddenExact.includes(k) || k.startsWith("Photo of") || /\d+ faces? available to add/i.test(k);
    };

    const getSharedByName = (container) => {
        const div = Array.from(container.querySelectorAll('div')).find(el => el.textContent.trim().startsWith('Shared by'));
        if (!div) return null;
        return div.textContent.replace(/Shared by\s+/i, '').replace(/Saved to your photos/i, '').trim();
    };

    const getAlbumName = () => {
        const title = document.title || "";
        const match = title.match(/(?:Photo|Video) in (.*?) - Google Photos/i);
        if (match && match[1]) {
            return match[1].replace(/[<>:"\/\\|?*]+/g, '_').trim();
        }
        return "google_photos_export";
    };

    const getSnapshot = () => {
        const h1s = Array.from(document.querySelectorAll('h1'));
        const visibleInfoH1s = h1s.filter(el => el.textContent.trim() === 'Info' && isVisible(el));
        let combinedEntries = [];

        visibleInfoH1s.forEach((h1) => {
            try {
                const grandParent = h1.parentElement?.parentElement;
                if (grandParent && grandParent.tagName === 'DIV') {
                    const elements = Array.from(grandParent.querySelectorAll('[aria-label]')).map(el => {
                        let key = el.getAttribute('aria-label') || "";
                        let value = el.innerText.trim();
                        if (key.includes(':')) key = key.split(':')[0].trim();
                        if (!key && value.startsWith('ISO')) key = 'ISO';
                        if (/^GMT[+-]\d+$/i.test(key.trim())) {
                            key = "Timezone";
                        }
                        return { key, value };
                    }).filter(item => item.key && item.value && !isBlacklisted(item.key));

                    const mapsLink = grandParent.querySelector('a[title="Show location of photo on Google Maps"]');
                    if (mapsLink && mapsLink.href) {
                        const coordsMatch = mapsLink.href.match(/([\d.-]+),([\d.-]+)/);
                        if (coordsMatch) {
                            elements.push({ key: "Coordinates", value: `${coordsMatch[1]}, ${coordsMatch[2]}` });
                        }
                    }

                    const sharedName = getSharedByName(grandParent);
                    if (sharedName) {
                        elements.push({ key: "Shared by", value: sharedName });
                    }
                    combinedEntries = combinedEntries.concat(elements);
                }
            } catch (err) { }
        });
        return combinedEntries.length > 0 ? combinedEntries : null;
    };

    const waitForStability = async () => {
        const startTime = Date.now();
        let stableCount = 0;
        let lastCandidateString = null;

        while (Date.now() - startTime < MAX_TIMEOUT) {
            const currentData = getSnapshot();
            const currentString = JSON.stringify(currentData);
            const hasName = currentData?.some(item => item.key === "Shared by");

            if (currentString && currentString === lastCandidateString && hasName) {
                stableCount++;
            } else {
                stableCount = 0;
                lastCandidateString = currentString;
            }

            if (stableCount >= STABILITY_RUN_REQUIRED) return currentData;
            await sleep(POLL_INTERVAL);
        }
        return null;
    };

    const jiggle = async () => {
        const prevButton = document.querySelector('[aria-label="View previous photo"]');
        const nextButton = document.querySelector('[aria-label="View next photo"]');
        if (!prevButton || !nextButton) return false;

        showToast(`🔄 Jiggling to recover UI state...`);
        prevButton.click();
        await sleep(1000);
        nextButton.click();
        await sleep(500);
        return true;
    };

    const generateCsv = (snapshots) => {
        const processedRecords = snapshots.map(record => {
            let entry = {};
            record.forEach(item => {
                entry[item.key] = item.value;
            });
            return entry;
        });

        const allKeys = new Set();
        processedRecords.forEach(rec => Object.keys(rec).forEach(k => allKeys.add(k)));

        const firstThree = ["Date taken", "Time taken", "Timezone"];
        firstThree.forEach(k => allKeys.delete(k));
        const headers = [...firstThree, ...Array.from(allKeys)];

        const csvRows = [headers.map(h => `"${h.replace(/"/g, '""')}"`).join(',')];

        processedRecords.forEach(rec => {
            const row = headers.map(header => `"${(rec[header] || '').replace(/"/g, '""')}"`);
            csvRows.push(row.join(','));
        });

        return csvRows.join('\n');
    };

    const downloadBlob = (content, filename) => {
        const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        link.setAttribute("href", URL.createObjectURL(blob));
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    showToast("🚀 Starting automation...", 3000);

    while (true) {
        let currentData = await waitForStability();

        if (!currentData) {
            if (!hasJiggledForCurrentTransition) {
                hasJiggledForCurrentTransition = true;
                if (await jiggle()) continue;
            }
            break;
        }

        const currentDataString = JSON.stringify(currentData);

        if (window.allSnapshots.length > 0) {
            const lastSavedDataString = JSON.stringify(window.allSnapshots[window.allSnapshots.length - 1]);
            if (currentDataString === lastSavedDataString) {
                showToast("🏁 End of album detected.", 4000);
                break;
            }
        }

        window.allSnapshots.push(currentData);
        hasJiggledForCurrentTransition = false;
        showToast(`📸 Captured snapshot ${window.allSnapshots.length}`, 1500);

        const nextButton = document.querySelector('[aria-label="View next photo"]');
        if (!nextButton || nextButton.getAttribute('aria-disabled') === 'true') break;

        nextButton.click();
        await sleep(250);

        const startTime = Date.now();
        let hasChanged = false;

        while (Date.now() - startTime < 3000) {
            const nextCandidate = getSnapshot();
            if (nextCandidate && JSON.stringify(nextCandidate) !== currentDataString) {
                hasChanged = true;
                break;
            }
            await sleep(POLL_INTERVAL);
        }

        if (!hasChanged) {
            if (!hasJiggledForCurrentTransition) {
                hasJiggledForCurrentTransition = true;
                if (await jiggle()) continue;
            } else {
                break;
            }
        }
    }

    showToast("✅ Finalizing CSV...", 4000);
    const csvOutput = generateCsv(window.allSnapshots);
    const albumTitle = getAlbumName();
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    downloadBlob(csvOutput, `${albumTitle}_${timestamp}.csv`);
    window.finalCsv = csvOutput;
})();
