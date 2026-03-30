// Enhanced JavaScript Functionality for Web Analyzer

document.addEventListener('DOMContentLoaded', function() {
  // Initialize all enhanced components
  initProgressBar();
  initURLValidation();
  initFormSubmissionHandling();
  initHoverEffects();
  initFuturisticElements();
  initLoadingOverlay();
  initTooltips();
  initDownloadButtons();  // Add download button handler
});

// Initialize download CSV button handlers
function initDownloadButtons() {
  document.addEventListener('click', function(e) {
    // Check if the clicked element is a download button
    if (e.target.classList.contains('download-csv-btn') ||
        e.target.closest('.download-csv-btn')) {
      e.preventDefault();

      const btn = e.target.classList.contains('download-csv-btn') ?
                  e.target : e.target.closest('.download-csv-btn');

      const url = btn.getAttribute('data-url');
      const respectRobots = btn.getAttribute('data-respectrobots') || 'true';

      if (!url) {
        alert('No URL specified for download');
        return;
      }

      // Build download URL
      const downloadUrl = `/download_url?url=${encodeURIComponent(url)}&respect_robots=${respectRobots}`;

      // Trigger download
      window.location.href = downloadUrl;
    }
  });
}

// Create progress bar for loading feedback
function initProgressBar() {
  // Create progress bar element if doesn't exist
  if (!document.getElementById('top-progress-bar')) {
    const progressBar = document.createElement('div');
    progressBar.className = 'progress';
    progressBar.id = 'top-progress-bar';
    progressBar.style.display = 'none';

    const progressBarInner = document.createElement('div');
    progressBarInner.className = 'progress-bar';
    progressBarInner.style.width = '0%';

    progressBar.appendChild(progressBarInner);
    document.body.prepend(progressBar);
  }
}

// Show progress bar animation
function showProgressBar() {
  const progressBar = document.getElementById('top-progress-bar');
  if (progressBar) {
    progressBar.style.display = 'block';
    const progressBarInner = progressBar.querySelector('.progress-bar');
    progressBarInner.style.width = '30%';

    setTimeout(() => {
      progressBarInner.style.width = '60%';
    }, 500);

    setTimeout(() => {
      progressBarInner.style.width = '80%';
    }, 1500);
  }
}

// Hide progress bar animation
function hideProgressBar() {
  const progressBar = document.getElementById('top-progress-bar');
  if (progressBar) {
    const progressBarInner = progressBar.querySelector('.progress-bar');
    progressBarInner.style.width = '100%';

    setTimeout(() => {
      progressBar.style.display = 'none';
      progressBarInner.style.width = '0%';
    }, 300);
  }
}

// Enhanced URL validation with visual feedback
function initURLValidation() {
  const urlInputs = document.querySelectorAll('input[type="url"], input[id="url"]');

  urlInputs.forEach(input => {
    // Create URL scanner effect container
    const parentElement = input.parentElement;
    const urlScannerContainer = document.createElement('div');
    urlScannerContainer.className = 'url-scanner-container';

    // Scanner line effect
    const scannerLine = document.createElement('div');
    scannerLine.className = 'url-scanner-line';
    urlScannerContainer.appendChild(scannerLine);

    // Wrap input with scanner container
    parentElement.insertBefore(urlScannerContainer, input);
    urlScannerContainer.appendChild(input);

    // URL validation function
    function validateAndFormatURL() {
      const url = input.value.trim();

      // Skip if empty
      if (!url) return;

      // Check URL validity
      let formattedURL = url;

      // Remove existing protocols to prevent doubling
      formattedURL = formattedURL.replace(/^(https?:\/\/)?(www\.)?/i, '');

      // Check if URL is potentially valid
      if (formattedURL.indexOf('.') !== -1) {
        const preferHttp = url.includes('http:') || url.toLowerCase().includes('http://');

        // Add proper protocol
        formattedURL = preferHttp ? 'http://' + formattedURL : 'https://' + formattedURL;

        // Visual validation feedback
        if (isValidURL(formattedURL)) {
          input.classList.remove('is-invalid');
          input.classList.add('is-valid');
          urlScannerContainer.classList.add('url-scanner-active');

          // Add glow effect for valid URL
          input.style.boxShadow = '0 0 5px rgba(16, 185, 129, 0.5)';
        } else {
          input.classList.remove('is-valid');
          input.classList.add('is-invalid');
          urlScannerContainer.classList.remove('url-scanner-active');

          // Add error glow
          input.style.boxShadow = '0 0 5px rgba(239, 68, 68, 0.5)';
        }

        // Update input value with formatted URL
        if (formattedURL !== url) {
          input.value = formattedURL;
        }
      }
    }

    // Check if string is potentially a valid URL
    function isValidURL(string) {
      try {
        new URL(string);
        return true;
      } catch (_) {
        return false;
      }
    }

    // Add input event listeners
    input.addEventListener('input', debounce(validateAndFormatURL, 500));
    input.addEventListener('blur', validateAndFormatURL);
    input.addEventListener('focus', () => {
      // Remove validation styles when focused
      input.classList.remove('is-valid', 'is-invalid');
      input.style.boxShadow = '';
    });
  });
}

// Debounce function to prevent excessive validation
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Handle form submissions with visual feedback
function initFormSubmissionHandling() {
  const forms = document.querySelectorAll('form');

  forms.forEach(form => {
    form.addEventListener('submit', function(e) {
      // Show loading state visual feedback
      showProgressBar();

      // If using AJAX (for URL search), prevent default
      if (form.id === 'urlSearchForm' && window.fetch) {
        e.preventDefault();

        // Show loading overlay
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
          loadingOverlay.style.display = 'flex';
        }

        // Get form data
        const formData = new FormData(form);
        const urlInput = form.querySelector('#url');

        // Ensure URL has proper format
        if (urlInput) {
          urlInput.value = ensureHttpsPrefix(urlInput.value);
          formData.set('url', urlInput.value);
        }

        // Set respect_robots to true (mandatory)
        formData.set('respect_robots', 'on');

        // Get the form's action URL
        const actionUrl = form.getAttribute('action').replace('url_search', 'url_search_ajax');

        // Send AJAX request
        fetch(actionUrl, {
          method: 'POST',
          body: formData,
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
        .then(response => {
          if (!response.ok) {
            throw new Error('Network response was not ok');
          }
          return response.text();
        })
        .then(html => {
          // Update results container
          const resultsContainer = document.getElementById('results-container');
          if (resultsContainer) {
            resultsContainer.innerHTML = html;

            // Add animation class to new content
            const newElements = resultsContainer.querySelectorAll('.card');
            newElements.forEach((el, index) => {
              // Stagger animations
              setTimeout(() => {
                el.classList.add('animate-fade-in');
              }, index * 100);
            });
          }

          // Re-initialize download buttons for newly loaded content
          initDownloadButtons();

          // Add event listeners to new buttons
          initHoverEffects();

          // Hide loading indicators
          hideProgressBar();
          if (loadingOverlay) {
            loadingOverlay.style.display = 'none';
          }

          // Record search history if function exists
          if (typeof recordSearch === 'function') {
            recordSearch(urlInput.value, 'URL Search');
          }
        })
        .catch(error => {
          console.error('Error:', error);
          if (document.getElementById('results-container')) {
            document.getElementById('results-container').innerHTML =
              `<div class="alert alert-danger">Error: ${error.message}</div>`;
          }

          // Hide loading indicators
          hideProgressBar();
          if (loadingOverlay) {
            loadingOverlay.style.display = 'none';
          }
        });
      } else {
        // For regular form submission, show loading overlay
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
          loadingOverlay.style.display = 'flex';
        }
      }
    });
  });
}

// Helper function for URL formatting
function ensureHttpsPrefix(url) {
  // Trim whitespace
  url = url.trim();

  // If URL is empty, return empty string
  if (!url) return '';

  // Remove any existing http:// or https:// to prevent doubling
  url = url.replace(/^(https?:\/\/)?(www\.)?/i, '');

  // Check if the URL is valid (contains at least one dot)
  if (url.indexOf('.') === -1) {
    return url; // Not a valid domain, don't modify
  }

  // Check if user typed http:// explicitly somewhere in the input
  const preferHttp = url.includes('http:') || url.toLowerCase().includes('http://');

  // Add proper protocol
  return preferHttp ? 'http://' + url : 'https://' + url;
}

// Add interactive hover effects
function initHoverEffects() {
  // Enhanced table row hover effect
  const tableRows = document.querySelectorAll('tbody tr');
  tableRows.forEach(row => {
    row.addEventListener('mouseenter', function() {
      this.style.transform = 'translateX(5px)';
      this.style.transition = 'transform 0.2s ease';
    });

    row.addEventListener('mouseleave', function() {
      this.style.transform = 'translateX(0)';
    });
  });

  // Action button hover effects
  const actionButtons = document.querySelectorAll('.btn-primary, .btn-outline-primary, .btn-outline-secondary');
  actionButtons.forEach(btn => {
    if (!btn.classList.contains('enhanced')) {
      btn.classList.add('enhanced', 'action-btn');

      // Add hover state that reveals subtle gradient
      btn.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-2px)';
        if (this.classList.contains('btn-primary')) {
          this.style.boxShadow = '0 6px 12px rgba(99, 102, 241, 0.3)';
        }
      });

      btn.addEventListener('mouseleave', function() {
        this.style.transform = '';
        this.style.boxShadow = '';
      });
    }
  });
}

// Add futuristic UI elements
function initFuturisticElements() {
  // Enhance headings with gradient effect
  const headings = document.querySelectorAll('h1');
  headings.forEach(heading => {
    if (!heading.classList.contains('enhanced')) {
      heading.classList.add('enhanced');
      heading.innerHTML = `<span class="heading-text">${heading.textContent}</span>`;
    }
  });

  // Add futuristic card design to table container
  const tableContainers = document.querySelectorAll('.table-responsive');
  tableContainers.forEach(container => {
    if (!container.classList.contains('enhanced')) {
      container.classList.add('enhanced', 'results-card');
    }
  });

  // Add subtle animation to checkbox
  const checkboxes = document.querySelectorAll('.form-check-input');
  checkboxes.forEach(checkbox => {
    checkbox.addEventListener('change', function() {
      if (this.checked) {
        this.style.animation = 'pulse 0.5s ease';
      }
    });
  });

  // Replace traditional loading spinner with futuristic hexagon spinner
  const loadingOverlay = document.getElementById('loading-overlay');
  if (loadingOverlay) {
    const spinner = loadingOverlay.querySelector('.spinner-border');
    if (spinner) {
      const hexSpinner = document.createElement('div');
      hexSpinner.className = 'hexagon-spinner';

      // Replace spinner
      spinner.parentNode.replaceChild(hexSpinner, spinner);

      // Add loading text
      const loadingText = document.createElement('div');
      loadingText.textContent = 'Analyzing...';
      loadingText.style.color = 'var(--text)';
      loadingText.style.marginTop = '15px';
      loadingText.style.fontSize = '0.9rem';
      loadingText.style.fontWeight = '500';
      loadingText.style.opacity = '0.8';
      loadingOverlay.appendChild(loadingText);
    }
  }
}

// Enhanced loading overlay
function initLoadingOverlay() {
  // Create loading overlay if it doesn't exist
  if (!document.getElementById('loading-overlay')) {
    const overlay = document.createElement('div');
    overlay.id = 'loading-overlay';
    overlay.style.display = 'none';
    overlay.style.position = 'fixed';
    overlay.style.top = '0';
    overlay.style.left = '0';
    overlay.style.width = '100%';
    overlay.style.height = '100%';
    overlay.style.backgroundColor = 'rgba(15, 23, 42, 0.8)';
    overlay.style.backdropFilter = 'blur(5px)';
    overlay.style.zIndex = '9999';
    overlay.style.display = 'none';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';
    overlay.style.flexDirection = 'column';

    const spinner = document.createElement('div');
    spinner.className = 'hexagon-spinner';

    const loadingText = document.createElement('div');
    loadingText.textContent = 'Analyzing...';
    loadingText.style.color = 'var(--text)';
    loadingText.style.marginTop = '15px';
    loadingText.style.fontSize = '0.9rem';
    loadingText.style.fontWeight = '500';
    loadingText.style.opacity = '0.8';

    overlay.appendChild(spinner);
    overlay.appendChild(loadingText);
    document.body.appendChild(overlay);
  }
}

// Add enhanced tooltips
function initTooltips() {
  // Find all elements that should have tooltips
  const tooltipElements = document.querySelectorAll('[data-tooltip]');

  tooltipElements.forEach(element => {
    const tooltipText = element.getAttribute('data-tooltip');
    if (!tooltipText) return;

    // Create tooltip element if it doesn't exist
    if (!element.querySelector('.custom-tooltip')) {
      const tooltip = document.createElement('span');
      tooltip.className = 'custom-tooltip';
      tooltip.textContent = tooltipText;
      element.style.position = 'relative';
      element.appendChild(tooltip);

      // Position the tooltip
      element.addEventListener('mouseenter', () => {
        const tooltip = element.querySelector('.custom-tooltip');
        tooltip.style.opacity = '1';
        tooltip.style.visibility = 'visible';

        // Position above the element
        tooltip.style.bottom = 'calc(100% + 10px)';
        tooltip.style.left = '50%';
        tooltip.style.transform = 'translateX(-50%)';
      });

      element.addEventListener('mouseleave', () => {
        const tooltip = element.querySelector('.custom-tooltip');
        tooltip.style.opacity = '0';
        tooltip.style.visibility = 'hidden';
      });
    }
  });

  // Add tooltips to action buttons
  document.querySelectorAll('.btn-primary').forEach(btn => {
    if (!btn.hasAttribute('data-tooltip') && !btn.querySelector('.custom-tooltip')) {
      // Get button text
      const btnText = btn.textContent.trim();
      let tooltipText = '';

      // Determine tooltip text based on button text
      if (btnText.includes('Analyze') || btnText.includes('View')) {
        tooltipText = 'Run detailed analysis on this URL';
      } else if (btnText.includes('Download')) {
        tooltipText = 'Download results as CSV file';
      }

      if (tooltipText) {
        btn.setAttribute('data-tooltip', tooltipText);

        // Create tooltip element
        const tooltip = document.createElement('span');
        tooltip.className = 'custom-tooltip';
        tooltip.textContent = tooltipText;
        btn.style.position = 'relative';
        btn.appendChild(tooltip);

        // Position the tooltip
        btn.addEventListener('mouseenter', () => {
          const tooltip = btn.querySelector('.custom-tooltip');
          if (tooltip) {
            tooltip.style.opacity = '1';
            tooltip.style.visibility = 'visible';

            // Position above the button
            tooltip.style.bottom = 'calc(100% + 10px)';
            tooltip.style.left = '50%';
            tooltip.style.transform = 'translateX(-50%)';
          }
        });

        btn.addEventListener('mouseleave', () => {
          const tooltip = btn.querySelector('.custom-tooltip');
          if (tooltip) {
            tooltip.style.opacity = '0';
            tooltip.style.visibility = 'hidden';
          }
        });
      }
    }
  });
}

// Add pulse animation keyframes to document
function addAnimationStyles() {
  if (!document.getElementById('enhanced-animations')) {
    const style = document.createElement('style');
    style.id = 'enhanced-animations';
    style.textContent = `
      @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.05); }
        100% { transform: scale(1); }
      }

      @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
      }

      .animate-fade-in {
        animation: fadeIn 0.5s ease forwards;
      }
    `;
    document.head.appendChild(style);
  }
}

// Call animation styles
addAnimationStyles();
