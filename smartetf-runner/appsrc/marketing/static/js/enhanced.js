// This extends your existing main.js with additional functionality for interactive elements

document.addEventListener('DOMContentLoaded', function() {
    // If these functions don't exist in your main.js, they will be added
    if (typeof createMarketDipChart !== 'function') {
        // Initialize interactive charts
        createMarketDipChart();
        createAlgorithmChart();
        createPerformanceChart();
        createCalculatorChart();
    }
    
    // Initialize calculator if not already initialized
    if (typeof initializeCalculator !== 'function') {
        initializeCalculator();
    }
    
    // Mobile menu toggle (only if not already handled)
    const mobileToggle = document.querySelector('.mobile-toggle');
    const navLinks = document.querySelector('.nav-links');
    
    if (mobileToggle && navLinks) {
        mobileToggle.addEventListener('click', function() {
            navLinks.classList.toggle('active');
        });
    }

    // Make all images interactive
    makeImagesInteractive();
});

// Make static images interactive
function makeImagesInteractive() {
    const images = document.querySelectorAll('img:not(.logo)');
    images.forEach(img => {
        // Don't process if already enhanced
        if (img.classList.contains('interactive')) return;
        
        // Add interactive class
        img.classList.add('interactive');
        
        // Add animation on scroll class if your existing system supports it
        if (typeof window.animateOnScroll === 'function') {
            img.classList.add('animate-on-scroll');
        }
        
        // Wrap image in interactive container if not already wrapped
        if (img.parentElement.tagName !== 'DIV' || !img.parentElement.classList.contains('img-container')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'img-container';
            img.parentNode.insertBefore(wrapper, img);
            wrapper.appendChild(img);
        }
    });
}

// Chart functions - these will only be used if not defined in your HTML

// Create Market Dip Chart
function createMarketDipChart() {
    const ctx = document.getElementById('marketDipChart');
    if (!ctx) return;
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
            datasets: [{
                label: 'Market Index',
                data: [100, 105, 103, 87, 92, 97, 94, 85, 89, 95, 101, 105],
                backgroundColor: 'rgba(67, 97, 238, 0.2)',
                borderColor: 'rgba(67, 97, 238, 1)',
                borderWidth: 2,
                pointBackgroundColor: '#fff',
                pointBorderColor: 'rgba(67, 97, 238, 1)',
                pointRadius: 5,
                pointHoverRadius: 7,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: false
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `Value: ${context.parsed.y}`;
                        }
                    }
                }
            }
        }
    });
}

// Create Algorithm Chart
function createAlgorithmChart() {
    const ctx = document.getElementById('algorithmChart');
    if (!ctx) return;
    
    new Chart(ctx, {
        type: 'radar',
        data: {
            labels: [
                'Market Timing',
                'ETF Selection',
                'Risk Management',
                'Cost Efficiency',
                'Tax Efficiency',
                'Diversification'
            ],
            datasets: [{
                label: 'SmartETF Algo',
                data: [85, 90, 80, 95, 85, 90],
                backgroundColor: 'rgba(67, 97, 238, 0.2)',
                borderColor: 'rgba(67, 97, 238, 1)',
                borderWidth: 2,
                pointBackgroundColor: '#fff',
                pointBorderColor: 'rgba(67, 97, 238, 1)',
                pointRadius: 4
            }, {
                label: 'Traditional Funds',
                data: [40, 60, 65, 50, 60, 75],
                backgroundColor: 'rgba(114, 9, 183, 0.2)',
                borderColor: 'rgba(114, 9, 183, 1)',
                borderWidth: 2,
                pointBackgroundColor: '#fff',
                pointBorderColor: 'rgba(114, 9, 183, 1)',
                pointRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    beginAtZero: true,
                    max: 100,
                    ticks: {
                        display: false
                    }
                }
            }
        }
    });
}

// Create Performance Chart
function createPerformanceChart() {
    const ctx = document.getElementById('performanceChart');
    if (!ctx) return;
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['2018', '2019', '2020', '2021', '2022', '2023', '2024'],
            datasets: [{
                label: 'SmartETF Algo',
                data: [100, 125, 145, 180, 210, 250, 300],
                backgroundColor: 'rgba(67, 97, 238, 0.2)',
                borderColor: 'rgba(67, 97, 238, 1)',
                borderWidth: 3,
                tension: 0.3
            }, {
                label: 'Average Mutual Fund',
                data: [100, 110, 118, 130, 142, 155, 170],
                backgroundColor: 'rgba(114, 9, 183, 0.2)',
                borderColor: 'rgba(114, 9, 183, 1)',
                borderWidth: 3,
                tension: 0.3
            }, {
                label: 'Market Index',
                data: [100, 115, 125, 145, 160, 180, 200],
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 3,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                y: {
                    title: {
                        display: true,
                        text: 'Value (₹)'
                    }
                }
            }
        }
    });
}

// Create Calculator Chart
function createCalculatorChart() {
    const ctx = document.getElementById('calculatorChart');
    if (!ctx) return;
    
    window.calculatorChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: Array.from({length: 11}, (_, i) => i),
            datasets: [{
                label: 'SmartETF Algo',
                data: calculateGrowth(10000, 10, 0.20),
                backgroundColor: 'rgba(67, 97, 238, 0.2)',
                borderColor: 'rgba(67, 97, 238, 1)',
                borderWidth: 3,
                tension: 0.3
            }, {
                label: 'Mutual Fund',
                data: calculateGrowth(10000, 10, 0.10),
                backgroundColor: 'rgba(114, 9, 183, 0.2)',
                borderColor: 'rgba(114, 9, 183, 1)',
                borderWidth: 3,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    title: {
                        display: true,
                        text: 'Value (₹)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '₹' + value.toLocaleString('en-IN');
                        }
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Years'
                    }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ₹' + context.parsed.y.toLocaleString('en-IN');
                        }
                    }
                }
            }
        }
    });
}

// Initialize Calculator
function initializeCalculator() {
    const monthlyInvestmentSlider = document.getElementById('monthlyInvestment');
    const investmentPeriodSlider = document.getElementById('investmentPeriod');
    const mutualFundReturnSlider = document.getElementById('mutualFundReturn');
    const smartetfReturnSlider = document.getElementById('smartetfReturn');
    
    if (!monthlyInvestmentSlider || !investmentPeriodSlider || !mutualFundReturnSlider || !smartetfReturnSlider) return;
    
    const monthlyInvestmentValue = document.getElementById('monthlyInvestmentValue');
    const investmentPeriodValue = document.getElementById('investmentPeriodValue');
    const mutualFundReturnValue = document.getElementById('mutualFundReturnValue');
    const smartetfReturnValue = document.getElementById('smartetfReturnValue');
    const advantageValue = document.getElementById('advantageValue');
    const advantagePercentage = document.getElementById('advantagePercentage');
    
    // Initialize values
    updateCalculatorValues();
    
    // Add event listeners
    monthlyInvestmentSlider.addEventListener('input', updateCalculatorValues);
    investmentPeriodSlider.addEventListener('input', updateCalculatorValues);
    mutualFundReturnSlider.addEventListener('input', updateCalculatorValues);
    smartetfReturnSlider.addEventListener('input', updateCalculatorValues);
    
    // Function to update calculator values
    function updateCalculatorValues() {
        const monthlyInvestment = parseInt(monthlyInvestmentSlider.value);
        const investmentPeriod = parseInt(investmentPeriodSlider.value);
        const mutualFundReturn = parseFloat(mutualFundReturnSlider.value) / 100;
        const smartetfReturn = parseFloat(smartetfReturnSlider.value) / 100;
        
        // Update display values
        monthlyInvestmentValue.textContent = monthlyInvestment.toLocaleString('en-IN');
        investmentPeriodValue.textContent = investmentPeriod + ' years';
        mutualFundReturnValue.textContent = (mutualFundReturn * 100).toFixed(1) + '%';
        smartetfReturnValue.textContent = (smartetfReturn * 100).toFixed(1) + '%';
        
        // Calculate future values
        const mutualFundFV = calculateFutureValue(monthlyInvestment, investmentPeriod, mutualFundReturn);
        const smartetfFV = calculateFutureValue(monthlyInvestment, investmentPeriod, smartetfReturn);
        const advantage = smartetfFV - mutualFundFV;
        const advantagePct = (advantage / mutualFundFV) * 100;
        
        // Update result display
        advantageValue.textContent = '₹' + advantage.toLocaleString('en-IN');
        advantagePercentage.textContent = advantagePct.toFixed(1) + '%';
        
        // Update chart
        if (window.calculatorChart) {
            window.calculatorChart.data.labels = Array.from({length: investmentPeriod + 1}, (_, i) => i);
            window.calculatorChart.data.datasets[0].data = calculateGrowth(monthlyInvestment, investmentPeriod, smartetfReturn);
            window.calculatorChart.data.datasets[1].data = calculateGrowth(monthlyInvestment, investmentPeriod, mutualFundReturn);
            window.calculatorChart.update();
        }
    }
}

// Helper function to calculate future value
function calculateFutureValue(monthlyInvestment, years, annualReturn) {
    const monthlyRate = annualReturn / 12;
    const months = years * 12;
    const futureValue = monthlyInvestment * ((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate) * (1 + monthlyRate);
    return Math.round(futureValue);
}

// Helper function to calculate growth data points
function calculateGrowth(monthlyInvestment, years, annualReturn) {
    const data = [0]; // Start at 0
    for (let year = 1; year <= years; year++) {
        const futureValue = calculateFutureValue(monthlyInvestment, year, annualReturn);
        data.push(futureValue);
    }
    return data;
}