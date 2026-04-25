document.addEventListener('DOMContentLoaded', function() {
    // Scroll animations
    const animateOnScroll = function() {
        const elements = document.querySelectorAll('.animate-on-scroll');

        elements.forEach(element => {
            const elementPosition = element.getBoundingClientRect().top;
            const screenPosition = window.innerHeight / 1.2;

            if (elementPosition < screenPosition) {
                setTimeout(() => {
                    element.classList.add('animate-visible');
                }, element.dataset.delay || 0);
            }
        });
    };

    // Initialize animations
    animateOnScroll();

    // Listen for scroll events
    window.addEventListener('scroll', animateOnScroll);

    // FAQ accordion functionality
    const faqItems = document.querySelectorAll('.faq-question');

    faqItems.forEach(item => {
        item.addEventListener('click', function() {
            const parent = this.parentNode;

            // Close all other FAQ items
            document.querySelectorAll('.faq-item').forEach(faqItem => {
                if (faqItem !== parent) {
                    faqItem.classList.remove('active');
                }
            });

            // Toggle current FAQ item
            parent.classList.toggle('active');

            // Update icon
            const icon = this.querySelector('.faq-icon');
            if (parent.classList.contains('active')) {
                icon.textContent = '−';
            } else {
                icon.textContent = '+';
            }
        });
    });

    // Market Dip Chart - Enhanced to show only dips
    const marketDipCtx = document.getElementById('marketDipChart');
    if (marketDipCtx) {
        // Generate market data with visible dips
        const dataPoints = 100;
        const marketData = [];
        const buyPoints = new Array(dataPoints).fill(null);

        // Create more pronounced dips for demonstration
        for (let i = 0; i < dataPoints; i++) {
            let value = 50 + i/5;
            // Add some volatility
            value += Math.sin(i/5) * 15;

            // Create occasional sharper dips
            if (i % 20 === 15) {
                value -= 20;
            }

            marketData.push(value);

            // Identify buy points at the bottom of dips (only when we have a clear dip)
            if ((i > 2 && i < dataPoints-2) &&
                marketData[i] < marketData[i-1] && marketData[i] < marketData[i-2] &&
                marketData[i] <= marketData[i+1] && marketData[i] <= marketData[i+2]) {
                buyPoints[i] = marketData[i];
            }
        }

        const chart = new Chart(marketDipCtx, {
            type: 'line',
            data: {
                labels: Array.from({length: dataPoints}, (_, i) => i),
                datasets: [{
                    label: 'Market Price',
                    data: marketData,
                    borderColor: '#1a56db',
                    backgroundColor: 'rgba(79, 142, 247, 0.1)',
                    borderWidth: 3,
                    pointRadius: 0,
                    fill: true
                }, {
                    label: 'Buy Points',
                    data: buyPoints,
                    borderColor: '#10b981',
                    backgroundColor: '#10b981',
                    borderWidth: 0,
                    pointRadius: 8,
                    pointHoverRadius: 10
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'SmartETF Algo: Strategic Buying at Market Dips',
                        font: {
                            size: 16
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                if (context.dataset.label === 'Buy Points') {
                                    return 'Buy Point: ₹' + context.raw.toFixed(2);
                                }
                                return context.dataset.label + ': ₹' + context.raw.toFixed(2);
                            }
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'nearest'
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Time'
                        },
                        ticks: {
                            display: false
                        },
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Price (₹)'
                        }
                    }
                },
                animation: {
                    duration: 2000,
                    easing: 'easeOutQuart'
                }
            }
        });

        // Add animation to highlight buy points sequentially
        setTimeout(() => {
            animateBuyPoints(chart, buyPoints);
        }, 1000);
    }

    function animateBuyPoints(chart, buyPoints) {
        const indices = buyPoints.map((point, index) => point !== null ? index : -1).filter(idx => idx !== -1);
        let currentIndex = 0;

        const animationInterval = setInterval(() => {
            if (currentIndex >= indices.length) {
                clearInterval(animationInterval);
                return;
            }

            const idx = indices[currentIndex];

            // Highlight current buy point
            chart.data.datasets[1].pointBackgroundColor = Array(buyPoints.length).fill('#10b981').map((color, i) =>
                i === idx ? '#ff9500' : color
            );

            chart.data.datasets[1].pointRadius = Array(buyPoints.length).fill(8).map((size, i) =>
                i === idx ? 14 : 8
            );

            chart.update();

            // Reset and move to next point
            setTimeout(() => {
                chart.data.datasets[1].pointBackgroundColor = Array(buyPoints.length).fill('#10b981');
                chart.data.datasets[1].pointRadius = Array(buyPoints.length).fill(8);
                chart.update();
                currentIndex++;
            }, 800);

        }, 1200);
    }

    // Performance Comparison Chart - Enhanced to show 7-10% better returns
    const performanceCtx = document.getElementById('performanceChart');
    if (performanceCtx) {
        const years = [0, 5, 10, 15, 20];

        // Calculate mutual fund returns at 12% annual growth
        const mfRate = 0.12;
        const mutualFundData = years.map(year => {
            if (year === 0) return 100;
            return Math.round(100 * Math.pow(1 + mfRate, year));
        });

        // Calculate SmartETF returns at about 8% higher (20% annual)
        const algoRate = 0.20; // Using 20% for SmartETF, which is about 8% higher than 12%
        const smartetfData = years.map(year => {
            if (year === 0) return 100;
            return Math.round(100 * Math.pow(1 + algoRate, year));
        });

        // Calculate the advantage percentage at the 20-year mark
        const finalMf = mutualFundData[mutualFundData.length - 1];
        const finalSmartEtf = smartetfData[smartetfData.length - 1];
        const advantagePct = ((finalSmartEtf - finalMf) / finalMf * 100).toFixed(1);

        new Chart(performanceCtx, {
            type: 'line',
            data: {
                labels: years.map(y => y === 0 ? 'Start' : y + ' Years'),
                datasets: [{
                    label: 'Mutual Funds (12%)',
                    data: mutualFundData,
                    borderColor: '#94a3b8',
                    backgroundColor: 'rgba(148, 163, 184, 0.1)',
                    borderWidth: 3,
                    tension: 0.3,
                    fill: true
                }, {
                    label: 'SmartETF Algo (20%)',
                    data: smartetfData,
                    borderColor: '#1a56db',
                    backgroundColor: 'rgba(26, 86, 219, 0.1)',
                    borderWidth: 3,
                    tension: 0.3,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Performance Comparison Over Time',
                        font: {
                            size: 16
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': ' + context.raw + '%';
                            }
                        }
                    },
                    annotation: {
                        annotations: {
                            advantage: {
                                type: 'label',
                                content: [`${advantagePct}% higher returns`, 'with SmartETF Algo'],
                                position: {
                                    x: '80%',
                                    y: '60%'
                                },
                                backgroundColor: 'rgba(255, 255, 255, 0.8)',
                                borderColor: '#1a56db',
                                borderWidth: 2,
                                borderRadius: 6,
                                padding: 10,
                                font: {
                                    size: 14,
                                    weight: 'bold'
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Investment Period'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Growth (%)'
                        },
                        suggestedMin: 0
                    }
                },
                animation: {
                    duration: 2000,
                    easing: 'easeOutQuart'
                }
            }
        });
    }

    // Investment Calculator - Updated with new min/max/default values
    const monthlyInvestment = document.getElementById('monthlyInvestment');
    const monthlyInvestmentValue = document.getElementById('monthlyInvestmentValue');
    const investmentYears = document.getElementById('investmentYears');
    const investmentYearsValue = document.getElementById('investmentYearsValue');
    const mfReturn = document.getElementById('mfReturn');
    const mfReturnValue = document.getElementById('mfReturnValue');
    const algoReturn = document.getElementById('algoReturn');
    const algoReturnValue = document.getElementById('algoReturnValue');
    const advantageValue = document.getElementById('advantageValue');
    const advantagePercent = document.getElementById('advantagePercent');

    let calculatorChart = null;
    const calculatorCtx = document.getElementById('calculatorChart');

    // Initialize calculator
    if (monthlyInvestment && investmentYears) {
        // Update range constraints for SmartETF returns
        if (algoReturn) {
            algoReturn.min = "16";  // Minimum 16%
            algoReturn.max = "30";  // Maximum 30%
            algoReturn.value = "20"; // Default 20%
            algoReturnValue.textContent = "20%";
        }

        // Set up input change listeners
        monthlyInvestment.addEventListener('input', updateCalculator);
        investmentYears.addEventListener('input', updateCalculator);
        mfReturn.addEventListener('input', updateCalculator);
        algoReturn.addEventListener('input', updateCalculator);

        // Initialize
        updateCalculator();
    }

    // Update calculator values and chart
    function updateCalculator() {
        if (!monthlyInvestment || !investmentYears) return;

        const monthly = parseInt(monthlyInvestment.value);
        const years = parseInt(investmentYears.value);
        const mfRate = parseInt(mfReturn.value) / 100;
        const algoRate = parseInt(algoReturn.value) / 100;

        monthlyInvestmentValue.textContent = '₹' + monthly.toLocaleString();
        investmentYearsValue.textContent = years + ' years';
        mfReturnValue.textContent = mfReturn.value + '%';
        algoReturnValue.textContent = algoReturn.value + '%';

        // Calculate returns
        const months = years * 12;
        const totalInvested = monthly * months;

        // Calculate using compound interest formula for monthly investments
        const mfReturns = monthly * ((Math.pow(1 + mfRate/12, months) - 1) / (mfRate/12)) * (1 + mfRate/12);
        const algoReturns = monthly * ((Math.pow(1 + algoRate/12, months) - 1) / (algoRate/12)) * (1 + algoRate/12);

        const advantage = algoReturns - mfReturns;
        const advantagePct = (advantage / mfReturns) * 100;

        advantageValue.textContent = '₹' + Math.round(advantage).toLocaleString();
        advantagePercent.textContent = '(' + advantagePct.toFixed(1) + '% better than mutual funds)';

        // Update chart
        if (calculatorChart) {
            calculatorChart.destroy();
        }

        calculatorChart = new Chart(calculatorCtx, {
            type: 'bar',
            data: {
                labels: ['Total Investment', 'Mutual Funds', 'SmartETF Algo'],
                datasets: [{
                    label: 'Value (₹)',
                    data: [totalInvested, mfReturns, algoReturns],
                    backgroundColor: ['#64748b', '#94a3b8', '#1a56db'],
                    borderColor: ['#475569', '#64748b', '#1a56db'],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Projected Returns after ' + years + ' years',
                        font: {
                            size: 16
                        }
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return '₹' + Math.round(context.raw).toLocaleString();
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Value (₹)'
                        }
                    }
                },
                animation: {
                    duration: 1000,
                    easing: 'easeOutQuart'
                }
            }
        });
    }

    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();

            const target = document.querySelector(this.getAttribute('href'));
            if (!target) return;

            window.scrollTo({
                top: target.offsetTop - 100,
                behavior: 'smooth'
            });
        });
    });
});
