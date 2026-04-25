/**
 * Comprehensive Registration Form Validation
 * Real-time validation with visual feedback for all form fields
 */

class RegistrationValidator {
    constructor() {
        this.form = document.getElementById('registerForm');
        this.submitButton = document.getElementById('registerButton');
        this.fields = {};
        this.validationState = {};
        this.interactionState = {}; // Track if user has interacted with field
        this.fieldValidators = {};
        this.availabilityState = {
            username: { value: '', status: 'unknown', checking: false },
            email: { value: '', status: 'unknown', checking: false },
            mobile: { value: '', status: 'unknown', checking: false }
        };
        // Add abort controllers for canceling pending requests
        this.abortControllers = {
            username: null,
            email: null,
            mobile: null
        };

        this.initializeFields();
        this.setupValidation();
        this.setupRealTimeChecks();
    }

    initializeFields() {
        const fieldIds = [
            'username', 'email', 'full_name', 'mobile', 'address',
            'state', 'city', 'pin', 'password', 'confirm_password', 'terms_agree'
        ];

        fieldIds.forEach(id => {
            const field = document.getElementById(id);
            if (field) {
                this.fields[id] = field;
                this.validationState[id] = false;
                this.interactionState[id] = false;

                // Track interaction
                field.addEventListener('focus', () => {
                    this.interactionState[id] = true;
                });

                field.addEventListener('blur', () => {
                    if (this.interactionState[id]) {
                        this.validateField(id);
                    }
                });
            }
        });
    }

    setupValidation() {
        this.setupInputFormatting();
        this.setupFieldValidators();
        this.setupFormListeners();
    }

    setupRealTimeChecks() {
        // Setup availability checks with debouncing
        this.setupAvailabilityCheck('username', '/api/check_username');
        this.setupAvailabilityCheck('email', '/api/check_email');
        this.setupAvailabilityCheck('mobile', '/api/check_mobile');
    }

    setupFieldValidators() {
        // Username validation
        this.addFieldValidation('username', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['username']) {
                return value && value.length >= 3 && /^[a-zA-Z0-9_]+$/.test(value);
            }

            const feedback = this.createFeedbackElement('username');

            if (!value) {
                this.availabilityState.username.status = 'unknown';
                return this.showError(feedback, 'Username is required');
            }
            if (value.length < 3) {
                this.availabilityState.username.status = 'unknown';
                return this.showError(feedback, 'Username must be at least 3 characters');
            }
            if (value.length > 20) {
                this.availabilityState.username.status = 'unknown';
                return this.showError(feedback, 'Username must be at most 20 characters');
            }
            if (!/^[a-zA-Z0-9_]+$/.test(value)) {
                this.availabilityState.username.status = 'unknown';
                return this.showError(feedback, 'Username can only contain letters, numbers, and underscores');
            }

            return this.resolveAvailability('username', value, feedback);
        });

        // Email validation
        this.addFieldValidation('email', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['email']) {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                return value && emailRegex.test(value);
            }

            const feedback = this.createFeedbackElement('email');

            if (!value) {
                this.availabilityState.email.status = 'unknown';
                return this.showError(feedback, 'Email is required');
            }

            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
                this.availabilityState.email.status = 'unknown';
                return this.showError(feedback, 'Please enter a valid email address');
            }

            return this.resolveAvailability('email', value, feedback);
        });

        // Full name validation
        this.addFieldValidation('full_name', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['full_name']) {
                return value && value.length >= 3;
            }

            const feedback = this.createFeedbackElement('full_name');

            if (!value) {
                return this.showError(feedback, 'Full name is required');
            }
            if (value.length < 3) {
                return this.showError(feedback, 'Full name must be at least 3 characters');
            }

            return this.showSuccess(feedback, 'Valid name');
        });

        // Address validation
        this.addFieldValidation('address', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['address']) {
                return value && value.length >= 10;
            }

            const feedback = this.createFeedbackElement('address');

            if (!value) {
                return this.showError(feedback, 'Address is required');
            }
            if (value.length < 10) {
                return this.showError(feedback, 'Please enter a complete address');
            }

            return this.showSuccess(feedback, 'Valid address');
        });

        // State validation (dropdown)
        this.addFieldValidation('state', (value) => {
            // For dropdown, just check if selected
            return value && value.length > 0;
        });

        // City validation (dropdown)
        this.addFieldValidation('city', (value) => {
            // For dropdown, just check if selected
            return value && value.length > 0;
        });

        // PIN code validation
        this.addFieldValidation('pin', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['pin']) {
                return value && /^\d{6}$/.test(value);
            }

            const feedback = this.createFeedbackElement('pin');

            if (!value) {
                return this.showError(feedback, 'PIN code is required');
            }
            if (!/^\d{6}$/.test(value)) {
                return this.showError(feedback, 'PIN code must be exactly 6 digits');
            }

            return this.showSuccess(feedback, 'Valid PIN code');
        });

        // Mobile validation
        this.addFieldValidation('mobile', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['mobile']) {
                return value && /^\d{10}$/.test(value) && value[0] >= '6';
            }

            const feedback = this.createFeedbackElement('mobile');

            if (!value) {
                this.availabilityState.mobile.status = 'unknown';
                return this.showError(feedback, 'Mobile number is required');
            }
            if (!/^\d{10}$/.test(value)) {
                this.availabilityState.mobile.status = 'unknown';
                return this.showError(feedback, 'Mobile number must be exactly 10 digits');
            }
            if (value[0] < '6') {
                this.availabilityState.mobile.status = 'unknown';
                return this.showError(feedback, 'Mobile number must start with 6, 7, 8, or 9');
            }

            return this.resolveAvailability('mobile', value, feedback);
        });

        // Password validation
        this.addFieldValidation('password', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['password']) {
                return value && value.length >= 8;
            }

            const feedback = this.createFeedbackElement('password');

            if (!value) {
                return this.showError(feedback, 'Password is required');
            }

            const strength = this.calculatePasswordStrength(value);

            if (value.length < 8) {
                return this.showError(feedback, 'Password must be at least 8 characters');
            }

            if (strength < 3) {
                return this.showWarning(feedback, 'Password strength: Weak. Include uppercase, lowercase, numbers, and symbols');
            }

            if (strength === 3) {
                return this.showWarning(feedback, 'Password strength: Medium. Consider adding more variety');
            }

            return this.showSuccess(feedback, 'Password strength: Strong');
        });

        // Confirm password validation
        this.addFieldValidation('confirm_password', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['confirm_password']) {
                const password = this.fields.password.value;
                return value && value === password;
            }

            const feedback = this.createFeedbackElement('confirm_password');
            const password = this.fields.password.value;

            if (!value) {
                return this.showError(feedback, 'Please confirm your password');
            }

            if (value !== password) {
                return this.showError(feedback, 'Passwords do not match');
            }

            return this.showSuccess(feedback, 'Passwords match');
        });

        // Terms agreement validation
        this.addFieldValidation('terms_agree', (checked) => {
            return checked === true;
        });
    }

    setupFormListeners() {
        // Setup form submission
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
    }

    setupAvailabilityCheck(fieldName, endpoint) {
        const field = this.fields[fieldName];
        let timeout;

        field.addEventListener('input', () => {
            clearTimeout(timeout);

            // Cancel any pending request for this field
            if (this.abortControllers[fieldName]) {
                this.abortControllers[fieldName].abort();
                this.abortControllers[fieldName] = null;
            }

            const value = field.value.trim();
            const normalizedValue = this.normalizeAvailabilityValue(fieldName, value);
            
            // Clear availability state when user changes input
            if (this.availabilityState[fieldName].value !== normalizedValue) {
                this.availabilityState[fieldName] = {
                    value: normalizedValue,
                    status: 'unknown',
                    checking: false
                };
            }

            // Trigger validation to show proper feedback
            if (this.interactionState[fieldName]) {
                this.validateField(fieldName);
            }

            // Only check availability if format validation passes
            if (this.isAvailabilityFormatValid(fieldName, normalizedValue)) {
                timeout = setTimeout(() => {
                    this.checkAvailability(fieldName, normalizedValue, endpoint);
                }, 500); // Debounce for 500ms
            }
        });

        field.addEventListener('blur', () => {
            if (!this.interactionState[fieldName]) {
                return;
            }
            const normalizedValue = this.normalizeAvailabilityValue(fieldName, field.value);
            if (!this.isAvailabilityFormatValid(fieldName, normalizedValue)) {
                return;
            }
            const availability = this.availabilityState[fieldName];
            // Only check if we haven't checked this exact value yet
            if (availability.value !== normalizedValue || availability.status === 'unknown') {
                this.checkAvailability(fieldName, normalizedValue, endpoint);
            }
        });
    }

    async checkAvailability(fieldName, value, endpoint) {
        const field = this.fields[fieldName];
        const feedback = this.getFeedbackElement(fieldName);

        // Cancel any existing request
        if (this.abortControllers[fieldName]) {
            this.abortControllers[fieldName].abort();
        }

        // Create new abort controller
        const abortController = new AbortController();
        this.abortControllers[fieldName] = abortController;

        // Mark as checking
        this.availabilityState[fieldName].checking = true;
        
        // Show checking status
        if (this.interactionState[fieldName]) {
            this.showPending(feedback, 'Checking availability...');
        }

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [fieldName]: value }),
                signal: abortController.signal
            });

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            const data = await response.json();

            // Verify the field value hasn't changed since we started the request
            const currentValue = this.normalizeAvailabilityValue(fieldName, field.value.trim());
            if (currentValue !== value) {
                // Value has changed, ignore this response
                return;
            }

            // Update availability state
            this.availabilityState[fieldName] = {
                value: value,
                status: data.exists ? 'taken' : 'available',
                checking: false
            };

            // Clear abort controller
            this.abortControllers[fieldName] = null;

            // Update validation state and UI
            if (data.exists) {
                if (this.interactionState[fieldName]) {
                    this.showError(feedback, `${this.capitalizeFirst(fieldName)} is already taken`);
                }
                this.validationState[fieldName] = false;
            } else {
                if (this.interactionState[fieldName]) {
                    this.showSuccess(feedback, `${this.capitalizeFirst(fieldName)} is available`);
                }
                // Only mark as valid if format validation also passes
                const formatValid = this.isAvailabilityFormatValid(fieldName, value);
                this.validationState[fieldName] = formatValid;
            }

            this.updateSubmitButton();

        } catch (error) {
            // Ignore abort errors (user is still typing)
            if (error.name === 'AbortError') {
                return;
            }

            console.error('Availability check error:', error);
            
            // Only show error if this is still the current value
            const currentValue = this.normalizeAvailabilityValue(fieldName, field.value.trim());
            if (currentValue === value && this.interactionState[fieldName]) {
                this.showWarning(feedback, 'Unable to check availability. Please try again.');
            }

            this.availabilityState[fieldName] = {
                value: value,
                status: 'unknown',
                checking: false
            };
            this.validationState[fieldName] = false;
            this.abortControllers[fieldName] = null;
            this.updateSubmitButton();
        }
    }

    setupInputFormatting() {
        // Format mobile number - only digits
        this.fields.mobile.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/\D/g, '');
        });

        // Format PIN code - only digits
        this.fields.pin.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/\D/g, '');
        });

        // Format full_name - only letters and spaces (state/city are now dropdowns)
        if (this.fields.full_name && this.fields.full_name.tagName.toLowerCase() === 'input') {
            this.fields.full_name.addEventListener('input', (e) => {
                // Allow letters, spaces, and periods for names
                e.target.value = e.target.value.replace(/[^a-zA-Z\s\.]/g, '');
            });
        }

        // Username formatting - only letters, numbers, underscores
        this.fields.username.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/[^a-zA-Z0-9_]/g, '');
        });
    }

    addFieldValidation(fieldName, validationFn) {
        const field = this.fields[fieldName];

        const validate = () => {
            const value = fieldName === 'terms_agree' ? field.checked : field.value.trim();
            const isValid = validationFn(value);

            // Update validation state
            this.validationState[fieldName] = isValid;

            // Update submit button
            this.updateSubmitButton();

            return isValid;
        };

        // Store validator for later use
        this.fieldValidators[fieldName] = validate;

        // Attach to input event
        if (fieldName === 'terms_agree') {
            field.addEventListener('change', validate);
        } else {
            field.addEventListener('input', validate);
        }

        // Initial silent validation (no visual feedback)
        validate();
    }

    validateField(fieldName) {
        if (this.fieldValidators[fieldName]) {
            return this.fieldValidators[fieldName]();
        }
        return false;
    }

    resolveAvailability(fieldName, value, feedback) {
        const availability = this.availabilityState[fieldName];
        const normalizedValue = this.normalizeAvailabilityValue(fieldName, value);
        
        // If currently checking, show pending
        if (availability.checking) {
            return this.showPending(feedback, 'Checking availability...');
        }
        
        // If we have a result for this exact value
        if (availability.value === normalizedValue) {
            if (availability.status === 'available') {
                return this.showSuccess(feedback, `${this.capitalizeFirst(fieldName)} is available`);
            }
            if (availability.status === 'taken') {
                return this.showError(feedback, `${this.capitalizeFirst(fieldName)} is already taken`);
            }
        }
        
        // If we don't have availability info yet, show pending
        return this.showPending(feedback, 'Checking availability...');
    }

    isAvailabilityFormatValid(fieldName, value) {
        const trimmed = value.trim();
        if (!trimmed) {
            return false;
        }
        if (fieldName === 'username') {
            return trimmed.length >= 3 && trimmed.length <= 20 && /^[a-zA-Z0-9_]+$/.test(trimmed);
        }
        if (fieldName === 'email') {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(trimmed);
        }
        if (fieldName === 'mobile') {
            return /^\d{10}$/.test(trimmed) && trimmed[0] >= '6';
        }
        return false;
    }

    normalizeAvailabilityValue(fieldName, value) {
        const trimmed = value.trim();
        if (fieldName === 'email') {
            return trimmed.toLowerCase();
        }
        return trimmed;
    }

    createFeedbackElement(fieldName) {
        const existingFeedback = document.getElementById(`${fieldName}-feedback`);
        if (existingFeedback) return existingFeedback;

        const feedback = document.createElement('div');
        feedback.id = `${fieldName}-feedback`;
        feedback.className = 'validation-feedback';
        feedback.style.cssText = `
            font-size: 0.875rem;
            margin-top: 0.25rem;
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            transition: all 0.2s ease;
        `;

        const field = this.fields[fieldName];
        if (fieldName === 'mobile') {
            field.parentNode.parentNode.appendChild(feedback);
        } else {
            field.parentNode.appendChild(feedback);
        }

        return feedback;
    }

    getFeedbackElement(fieldName) {
        return document.getElementById(`${fieldName}-feedback`);
    }

    showError(element, message) {
        if (!element) return false;
        element.textContent = `❌ ${message}`;
        element.style.cssText += `
            color: #dc2626;
            background-color: #fef2f2;
            border: 1px solid #fecaca;
        `;
        return false;
    }

    showSuccess(element, message) {
        if (!element) return true;
        element.textContent = `✅ ${message}`;
        element.style.cssText += `
            color: #059669;
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
        `;
        return true;
    }

    showWarning(element, message) {
        if (!element) return false;
        element.textContent = `⚠️ ${message}`;
        element.style.cssText += `
            color: #d97706;
            background-color: #fffbeb;
            border: 1px solid #fde68a;
        `;
        return false;
    }

    showPending(element, message) {
        if (!element) return false;
        element.textContent = `🔄 ${message}`;
        element.style.cssText += `
            color: #64748b;
            background-color: #f8fafc;
            border: 1px solid #e5e7eb;
        `;
        return false;
    }

    calculatePasswordStrength(password) {
        let strength = 0;

        if (password.length >= 8) strength++;
        if (/[a-z]/.test(password)) strength++;
        if (/[A-Z]/.test(password)) strength++;
        if (/\d/.test(password)) strength++;
        if (/[^a-zA-Z0-9]/.test(password)) strength++;

        return strength;
    }

    updateSubmitButton() {
        const allValid = Object.values(this.validationState).every(state => state === true);
        
        // Also check if any availability checks are pending
        const anyChecking = Object.values(this.availabilityState).some(state => state.checking);
        
        this.submitButton.disabled = !allValid || anyChecking;

        if (anyChecking) {
            this.submitButton.textContent = 'Checking...';
            this.submitButton.classList.remove('btn-primary');
            this.submitButton.classList.add('btn-secondary');
        } else if (allValid) {
            this.submitButton.textContent = 'Register';
            this.submitButton.classList.remove('btn-secondary');
            this.submitButton.classList.add('btn-primary');
        } else {
            this.submitButton.textContent = 'Complete all fields';
            this.submitButton.classList.remove('btn-primary');
            this.submitButton.classList.add('btn-secondary');
        }
    }

    handleSubmit(e) {
        // Final validation before submission
        let allValid = true;
        let firstInvalidField = null;

        Object.keys(this.fields).forEach(fieldName => {
            const field = this.fields[fieldName];
            const value = fieldName === 'terms_agree' ? field.checked : field.value.trim();

            if (!value || (fieldName !== 'terms_agree' && value.length === 0)) {
                allValid = false;
                if (!firstInvalidField) {
                    firstInvalidField = field;
                }
            }

            // Check availability status for username, email, mobile
            if (['username', 'email', 'mobile'].includes(fieldName)) {
                const availability = this.availabilityState[fieldName];
                if (availability.status !== 'available') {
                    allValid = false;
                    if (!firstInvalidField) {
                        firstInvalidField = field;
                    }
                }
            }
        });

        if (!allValid) {
            e.preventDefault();
            this.showFormError('Please fill in all required fields correctly and ensure username, email, and mobile are available.');
            if (firstInvalidField) {
                firstInvalidField.focus();
            }
            return false;
        }

        // Check for specific availability issues
        if (this.availabilityState.username.status === 'taken') {
            e.preventDefault();
            this.showFormError('Username is already taken. Please choose a different username.');
            this.fields.username.focus();
            return false;
        }

        if (this.availabilityState.email.status === 'taken') {
            e.preventDefault();
            this.showFormError('Email is already registered. Please use a different email address.');
            this.fields.email.focus();
            return false;
        }

        if (this.availabilityState.mobile.status === 'taken') {
            e.preventDefault();
            this.showFormError('Mobile number is already registered. Please use a different mobile number.');
            this.fields.mobile.focus();
            return false;
        }

        if (!this.validationState.terms_agree) {
            e.preventDefault();
            this.showFormError('Please accept the Terms & Conditions to continue.');
            return false;
        }

        // Show loading state
        this.submitButton.disabled = true;
        this.submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating account...';

        return true;
    }

    showFormError(message) {
        // Remove existing alerts
        const existingAlert = document.querySelector('.form-error-alert');
        if (existingAlert) existingAlert.remove();

        const alert = document.createElement('div');
        alert.className = 'alert alert-danger alert-dismissible fade show form-error-alert';
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        this.form.insertBefore(alert, this.form.firstChild);
        alert.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    capitalizeFirst(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
}

// Initialize validation when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('registerForm')) {
        new RegistrationValidator();
    }
});
