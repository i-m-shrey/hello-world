// Global search functionality
document.addEventListener('DOMContentLoaded', function() {
    // Handle search input and buttons
    document.querySelectorAll('.input-group input[type="text"][id*="search"]').forEach(function(searchInput) {
        // Add event listener for enter key
        searchInput.addEventListener('keyup', function(event) {
            if (event.key === 'Enter') {
                performSearch(searchInput);
            }

            // For client-side filtering (like on users page)
            if (searchInput.id === 'search-users') {
                const searchTerm = searchInput.value.toLowerCase();
                const tableRows = document.querySelectorAll('tbody tr');

                tableRows.forEach(function(row) {
                    let matchFound = false;
                    // Check all cells in the row
                    row.querySelectorAll('td').forEach(function(cell) {
                        if (cell.textContent.toLowerCase().includes(searchTerm)) {
                            matchFound = true;
                        }
                    });

                    row.style.display = matchFound ? '' : 'none';
                });
            }
        });

        // Get the corresponding button
        const searchButton = searchInput.parentElement.querySelector('button');
        if (searchButton) {
            searchButton.addEventListener('click', function() {
                performSearch(searchInput);
            });
        }
    });

    function performSearch(searchInput) {
        // If it's part of a form, submit the form
        const form = searchInput.closest('form');
        if (form) {
            form.submit();
        } else {
            // Trigger the keyup event to perform client-side filtering
            const event = new Event('keyup');
            searchInput.dispatchEvent(event);
        }
    }

    // Toggle password visibility
    document.querySelectorAll('.toggle-password').forEach(function(button) {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const passwordField = document.querySelector(targetId);

            if (passwordField) {
                const type = passwordField.getAttribute('type') === 'password' ? 'text' : 'password';
                passwordField.setAttribute('type', type);

                const icon = this.querySelector('i');
                if (icon) {
                    if (type === 'text') {
                        icon.classList.remove('fa-eye');
                        icon.classList.add('fa-eye-slash');
                    } else {
                        icon.classList.remove('fa-eye-slash');
                        icon.classList.add('fa-eye');
                    }
                }
            }
        });
    });
});