// Global loading spinner
(function() {
    'use strict';

    // Disable the global page loader on the broker test-confirmation page.
    // That page has its own JS loaders and runs long in-page actions.
    const PATHNAME = (window.location && window.location.pathname) ? window.location.pathname : '';
    const DISABLE_GLOBAL_SPINNER = PATHNAME.startsWith('/broker/test-confirmation');

    // Create spinner HTML
    const spinnerHTML = `
        <div id="global-loading-spinner" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0, 0, 0, 0.7); z-index: 99999; justify-content: center; align-items: center;">
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;">
                <div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem; border-width: 0.3rem;">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <p style="font-size: 1.2rem; font-weight: 500; color: #fff; margin-top: 1rem;">Processing...</p>
            </div>
        </div>
    `;

    // Create spinner element
    function createSpinner() {
        if (document.body && !document.getElementById('global-loading-spinner')) {
            document.body.insertAdjacentHTML('beforeend', spinnerHTML);
        }
    }

    // Create immediately or wait for body (unless disabled for this page)
    if (!DISABLE_GLOBAL_SPINNER) {
        if (document.body) {
            createSpinner();
        } else {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', createSpinner);
            } else {
                createSpinner();
            }
        }
    }

    // Global show/hide functions
    window.showLoadingSpinner = function() {
        if (DISABLE_GLOBAL_SPINNER) return;
        const spinner = document.getElementById('global-loading-spinner');
        if (spinner) {
            spinner.style.display = 'flex';
        }
    };

    window.hideLoadingSpinner = function() {
        if (DISABLE_GLOBAL_SPINNER) return;
        const spinner = document.getElementById('global-loading-spinner');
        if (spinner) {
            spinner.style.display = 'none';
        }
    };

    // Attach event handlers
    function attachSpinnerHandlers() {
        if (DISABLE_GLOBAL_SPINNER) {
            return;
        }
        // Exclusion rules
        const excludedClasses = ['toggle-password', 'btn-close', 'navbar-toggler', 'no-spinner', 'dropdown-toggle'];
        const excludedHrefs = ['#', 'javascript:void(0)', 'javascript:;'];
        const excludedDataToggles = ['dropdown', 'collapse', 'modal'];

        function shouldExclude(element) {
            if (excludedClasses.some(cls => element.classList.contains(cls))) {
                return true;
            }

            const dataToggle = element.getAttribute('data-bs-toggle');
            if (dataToggle && excludedDataToggles.includes(dataToggle)) {
                return true;
            }

            if (element.getAttribute('data-bs-dismiss')) {
                return true;
            }

            if (element.closest('.modal')) {
                return true;
            }

            return false;
        }

        // Handle ALL form submissions
        document.querySelectorAll('form').forEach(function(form) {
            if (form.classList.contains('no-spinner')) {
                return;
            }

            form.addEventListener('submit', function(e) {
                window.showLoadingSpinner();
                setTimeout(window.hideLoadingSpinner, 30000);
            });
        });

        // Handle ALL links
        document.querySelectorAll('a').forEach(function(link) {
            if (shouldExclude(link)) {
                return;
            }

            const href = link.getAttribute('href');
            if (href && !excludedHrefs.includes(href.trim())) {
                link.addEventListener('click', function(e) {
                    // Don't show spinner if link has target="_blank"
                    if (link.getAttribute('target') === '_blank') {
                        return;
                    }

                    window.showLoadingSpinner();
                    setTimeout(window.hideLoadingSpinner, 30000);
                });
            }
        });

        // Handle standalone buttons (not in forms, not submit buttons)
        document.querySelectorAll('button').forEach(function(button) {
            if (shouldExclude(button)) {
                return;
            }

            if (button.type === 'submit' || button.closest('form')) {
                return;
            }

            const onclick = button.getAttribute('onclick');
            if (onclick && (onclick.includes('Modal') || onclick.includes('modal'))) {
                return;
            }

            button.addEventListener('click', function() {
                window.showLoadingSpinner();
                setTimeout(window.hideLoadingSpinner, 30000);
            });
        });
    }

    // Attach handlers when DOM is ready (unless disabled for this page)
    if (!DISABLE_GLOBAL_SPINNER) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', attachSpinnerHandlers);
        } else {
            attachSpinnerHandlers();
        }
    }

    // Hide spinner on page show
    window.addEventListener('pageshow', function() {
        window.hideLoadingSpinner();
    });

    // IMPORTANT:
    // Do NOT hide the spinner on beforeunload.
    // When a user clicks a link / submits a form, the browser fires beforeunload very quickly.
    // If we hide here, the spinner flashes for a split second and disappears (your current issue).
})();