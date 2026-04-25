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
        
        this.initializeFields();
        this.setupValidation();
        this.setupRealTimeChecks();
    }

    initializeFields() {
        this.fields = {
            username: document.getElementById('username'),
            email: document.getElementById('email'),
            full_name: document.getElementById('full_name'),
            address: document.getElementById('address'),
            state: document.getElementById('state'),
            city: document.getElementById('city'),
            pin: document.getElementById('pin'),
            mobile: document.getElementById('mobile'),
            password: document.getElementById('password'),
            confirm_password: document.getElementById('confirm_password'),
            terms_agree: document.getElementById('terms_agree')
        };

        // Initialize validation and interaction state
        Object.keys(this.fields).forEach(field => {
            this.validationState[field] = false;
            this.interactionState[field] = false; // Track user interaction
        });
    }

    setupValidation() {
        // Username validation
        this.addFieldValidation('username', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['username']) {
                return value.length >= 3 && value.length <= 20 && /^[a-zA-Z0-9_]+$/.test(value);
            }
            
            const feedback = this.createFeedbackElement('username');
            
            if (!value) {
                return this.showError(feedback, 'Username is required');
            }
            if (value.length < 3) {
                return this.showError(feedback, 'Username must be at least 3 characters');
            }
            if (value.length > 20) {
                return this.showError(feedback, 'Username must be less than 20 characters');
            }
            if (!/^[a-zA-Z0-9_]+$/.test(value)) {
                return this.showError(feedback, 'Username can only contain letters, numbers, and underscores');
            }
            
            return this.showPending(feedback, 'Checking availability...');
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
                return this.showError(feedback, 'Email is required');
            }
            
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
                return this.showError(feedback, 'Please enter a valid email address');
            }
            
            return this.showPending(feedback, 'Checking availability...');
        });

        // Full name validation
        this.addFieldValidation('full_name', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['full_name']) {
                return value && value.length >= 2 && value.length <= 100 && /^[a-zA-Z\s\.]+$/.test(value);
            }
            
            const feedback = this.createFeedbackElement('full_name');
            
            if (!value) {
                return this.showError(feedback, 'Full name is required');
            }
            if (value.length < 2) {
                return this.showError(feedback, 'Full name must be at least 2 characters');
            }
            if (value.length > 100) {
                return this.showError(feedback, 'Full name must be less than 100 characters');
            }
            if (!/^[a-zA-Z\s\.]+$/.test(value)) {
                return this.showError(feedback, 'Full name can only contain letters, spaces, and periods');
            }
            
            return this.showSuccess(feedback, 'Valid name');
        });

        // Address validation
        this.addFieldValidation('address', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['address']) {
                return value && value.length >= 10 && value.length <= 500;
            }
            
            const feedback = this.createFeedbackElement('address');
            
            if (!value) {
                return this.showError(feedback, 'Address is required');
            }
            if (value.length < 10) {
                return this.showError(feedback, 'Please enter a complete address (min 10 characters)');
            }
            if (value.length > 500) {
                return this.showError(feedback, 'Address is too long (max 500 characters)');
            }
            
            return this.showSuccess(feedback, 'Valid address');
        });

        // State validation
        this.addFieldValidation('state', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['state']) {
                return value && value.length >= 2 && /^[a-zA-Z\s]+$/.test(value);
            }
            
            const feedback = this.createFeedbackElement('state');
            
            if (!value) {
                return this.showError(feedback, 'State is required');
            }
            if (value.length < 2) {
                return this.showError(feedback, 'State name must be at least 2 characters');
            }
            if (!/^[a-zA-Z\s]+$/.test(value)) {
                return this.showError(feedback, 'State name can only contain letters and spaces');
            }
            
            return this.showSuccess(feedback, 'Valid state');
        });

        // City validation
        this.addFieldValidation('city', (value) => {
            // Only show feedback if user has interacted
            if (!this.interactionState['city']) {
                return value && value.length >= 2 && /^[a-zA-Z\s]+$/.test(value);
            }
            
            const feedback = this.createFeedbackElement('city');
            
            if (!value) {
                return this.showError(feedback, 'City is required');
            }
            if (value.length < 2) {
                return this.showError(feedback, 'City name must be at least 2 characters');
            }
            if (!/^[a-zA-Z\s]+$/.test(value)) {
                return this.showError(feedback, 'City name can only contain letters and spaces');
            }
            
            return this.showSuccess(feedback, 'Valid city');
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
                return this.showError(feedback, 'Mobile number is required');
            }
            if (!/^\d{10}$/.test(value)) {
                return this.showError(feedback, 'Mobile number must be exactly 10 digits');
            }
            if (value[0] < '6') {
                return this.showError(feedback, 'Mobile number must start with 6, 7, 8, or 9');
            }
            
            return this.showPending(feedback, 'Checking availability...');
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
            // No visual feedback for checkbox, just validation state
            // Always return the checked state
            return checked;
        });
    }

    setupRealTimeChecks() {
        // Setup availability checks for unique fields
        this.setupAvailabilityCheck('email', '/api/check_email');
        this.setupAvailabilityCheck('username', '/api/check_username');
        this.setupAvailabilityCheck('mobile', '/api/check_mobile');

        // Setup input formatting
        this.setupInputFormatting();

        // Setup form submission
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
    }

    setupAvailabilityCheck(fieldName, endpoint) {
        const field = this.fields[fieldName];
        let timeout;

        field.addEventListener('input', () => {
            clearTimeout(timeout);
            
            // Only check availability if user has interacted and basic validation passes
            if (this.interactionState[fieldName] && this.validationState[fieldName]) {
                timeout = setTimeout(() => {
                    this.checkAvailability(fieldName, field.value, endpoint);
                }, 500); // Debounce for 500ms
            }
        });
    }

    async checkAvailability(fieldName, value, endpoint) {
        const feedback = this.getFeedbackElement(fieldName);
        
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [fieldName]: value })
            });
            
            const data = await response.json();
            
            if (data.exists) {
                this.showError(feedback, `${this.capitalizeFirst(fieldName)} is already taken`);
                this.validationState[fieldName] = false;
            } else {
                this.showSuccess(feedback, `${this.capitalizeFirst(fieldName)} is available`);
                this.validationState[fieldName] = true;
            }
        } catch (error) {
            this.showWarning(feedback, 'Unable to check availability. Please try again.');
            this.validationState[fieldName] = false;
        }
        
        this.updateSubmitButton();
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

        // Format names - only letters and spaces
        ['full_name', 'state', 'city'].forEach(fieldName => {
            this.fields[fieldName].addEventListener('input', (e) => {
                // Allow letters, spaces, and periods for names
                e.target.value = e.target.value.replace(/[^a-zA-Z\s\.]/g, '');
            });
        });

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
            
            this.validationState[fieldName] = isValid;
            this.updateSubmitButton();
            
            return isValid;
        };

        // Add event listeners with interaction tracking
        if (fieldName === 'terms_agree') {
            field.addEventListener('change', () => {
                this.interactionState[fieldName] = true;
                validate();
            });
        } else {
            // Mark as interacted when user starts typing
            field.addEventListener('input', () => {
                this.interactionState[fieldName] = true;
                validate();
            });
            
            // Also validate on blur (when leaving field)
            field.addEventListener('blur', () => {
                this.interactionState[fieldName] = true;
                validate();
            });
        }

        // Initial silent validation (no visual feedback)
        validate();
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
        element.textContent = `❌ ${message}`;
        element.style.cssText += `
            color: #dc2626;
            background-color: #fef2f2;
            border: 1px solid #fecaca;
        `;
        return false;
    }

    showSuccess(element, message) {
        element.textContent = `✅ ${message}`;
        element.style.cssText += `
            color: #059669;
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
        `;
        return true;
    }

    showWarning(element, message) {
        element.textContent = `⚠️ ${message}`;
        element.style.cssText += `
            color: #d97706;
            background-color: #fffbeb;
            border: 1px solid #fed7aa;
        `;
        return false;
    }

    showPending(element, message) {
        element.textContent = `⏳ ${message}`;
        element.style.cssText += `
            color: #6b7280;
            background-color: #f9fafb;
            border: 1px solid #e5e7eb;
        `;
        return true;
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
        this.submitButton.disabled = !allValid;
        
        if (allValid) {
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
        
        Object.keys(this.fields).forEach(fieldName => {
            const field = this.fields[fieldName];
            const value = fieldName === 'terms_agree' ? field.checked : field.value.trim();
            
            if (!value || (fieldName !== 'terms_agree' && value.length === 0)) {
                allValid = false;
                field.focus();
            }
        });

        if (!allValid) {
            e.preventDefault();
            this.showFormError('Please fill in all required fields correctly.');
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