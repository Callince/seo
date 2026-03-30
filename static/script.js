// /static/script.js
document.getElementById("urlForm").addEventListener("submit", function(event) {
  event.preventDefault();
  const url = document.getElementById("urlInput").value;
  fetch("/extract_links", {
      method: "POST",
      body: new URLSearchParams({ url })
  })
  .then(response => response.json())
  .then(data => {
      document.getElementById("results").innerHTML = JSON.stringify(data, null, 2);
  });
});

document.addEventListener('DOMContentLoaded', function() {
  // Initialize all components
  initializeDashboardMetrics();
  initializeContentDistributionChart();
  initializeSitemapIssuesAnalysis();
  initializeURLTable();
  initializeDepthAnalysis();
  initializeSiteStructureVisualization();
  initializeAdvancedAnalysis();
  initializeModalHandlers();
  calculateSitemapScore();
});

/**
* Calculate and display the sitemap score based on multiple factors
*/
function calculateSitemapScore() {
  // Get sitemap data from the page
  const totalSitemaps = document.querySelectorAll('#sitemapsTable tbody tr').length;
  const totalUrls = document.querySelectorAll('#urlsTable tbody tr').length;
  const crawlableUrls = getCrawlableUrlsCount();
  const urlsWithLastmod = getUrlsWithLastmodCount();
  const urlsWithPriority = getUrlsWithPriorityCount();
  const urlsWithChangefreq = getUrlsWithChangefreqCount();

  // Calculate scores for different aspects (out of 100)
  const crawlabilityScore = (crawlableUrls / totalUrls) * 100;
  const metadataScore = ((urlsWithLastmod + urlsWithPriority + urlsWithChangefreq) / (totalUrls * 3)) * 100;
  const sitemapStructureScore = Math.min(100, totalSitemaps * 20); // Cap at 100

  // Calculate overall score (weighted average)
  const overallScore = Math.round(
      (crawlabilityScore * 0.4) +
      (metadataScore * 0.4) +
      (sitemapStructureScore * 0.2)
  );

  // Update score UI
  const scoreElement = document.getElementById('scoreValue');
  if (scoreElement) {
      scoreElement.textContent = overallScore;

      // Update score color based on value
      const scoreBadge = document.getElementById('sitemapScore');
      if (scoreBadge) {
          scoreBadge.classList.remove('bg-primary', 'bg-success', 'bg-warning', 'bg-danger');
          if (overallScore >= 80) {
              scoreBadge.classList.add('bg-success');
          } else if (overallScore >= 60) {
              scoreBadge.classList.add('bg-primary');
          } else if (overallScore >= 40) {
              scoreBadge.classList.add('bg-warning');
          } else {
              scoreBadge.classList.add('bg-danger');
          }
      }
  }
}

/**
* Initialize the dashboard metrics (URL density, crawlable percentage, etc.)
*/
function initializeDashboardMetrics() {
  // Calculate URL density
  const totalUrls = document.querySelectorAll('#urlsTable tbody tr').length;
  const urlDensityElement = document.getElementById('urlDensity');
  if (urlDensityElement) {
      const hostName = new URL(document.querySelector('.card-header a').href).hostname;
      urlDensityElement.textContent = `${Math.round(totalUrls / 10) * 10}+ URLs on ${hostName}`;
  }

  // Calculate crawlable percentage
  const crawlableUrls = getCrawlableUrlsCount();
  const crawlablePercentage = document.getElementById('crawlablePercentage');
  if (crawlablePercentage) {
      const percentage = (crawlableUrls / totalUrls) * 100;
      crawlablePercentage.style.width = `${percentage}%`;
  }

  // Calculate recently updated count
  const recentlyUpdated = document.getElementById('recentlyUpdated');
  const lastUpdatedDate = document.getElementById('lastUpdatedDate');
  if (recentlyUpdated && lastUpdatedDate) {
      const recentlyUpdatedCount = getRecentlyUpdatedCount();
      recentlyUpdated.textContent = recentlyUpdatedCount;

      // Find the most recent date
      const mostRecentDate = getMostRecentDate();
      if (mostRecentDate) {
          // Format the date nicely
          const formattedDate = new Date(mostRecentDate).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'short',
              day: 'numeric'
          });
          lastUpdatedDate.textContent = `Last update: ${formattedDate}`;
      } else {
          lastUpdatedDate.textContent = 'No update dates found';
      }
  }
}

/**
* Initialize the Content Distribution Chart
*/
function initializeContentDistributionChart() {
  const canvas = document.getElementById('contentDistributionChart');
  if (!canvas) return;

  // Count different content types
  const contentTypes = {
      'Webpage': 0,
      'Image': 0,
      'Document': 0,
      'Video': 0,
      'Other': 0
  };

  document.querySelectorAll('#urlsTable tbody tr').forEach(row => {
      const badgeElement = row.querySelector('.badge');
      if (badgeElement) {
          const contentType = badgeElement.textContent.trim();
          if (contentTypes.hasOwnProperty(contentType)) {
              contentTypes[contentType]++;
          } else {
              contentTypes['Other']++;
          }
      } else {
          contentTypes['Other']++;
      }
  });

  // Create the chart
  new Chart(canvas, {
      type: 'pie',
      data: {
          labels: Object.keys(contentTypes),
          datasets: [{
              data: Object.values(contentTypes),
              backgroundColor: [
                  'rgba(54, 162, 235, 0.7)',
                  'rgba(75, 192, 192, 0.7)',
                  'rgba(255, 159, 64, 0.7)',
                  'rgba(255, 99, 132, 0.7)',
                  'rgba(201, 203, 207, 0.7)'
              ],
              borderColor: [
                  'rgb(54, 162, 235)',
                  'rgb(75, 192, 192)',
                  'rgb(255, 159, 64)',
                  'rgb(255, 99, 132)',
                  'rgb(201, 203, 207)'
              ],
              borderWidth: 1
          }]
      },
      options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
              legend: {
                  position: 'right',
              },
              tooltip: {
                  callbacks: {
                      label: function(context) {
                          const label = context.label || '';
                          const value = context.raw || 0;
                          const total = context.dataset.data.reduce((a, b) => a + b, 0);
                          const percentage = Math.round((value / total) * 100);
                          return `${label}: ${value} (${percentage}%)`;
                      }
                  }
              }
          }
      }
  });
}

/**
* Initialize Sitemap Issues Analysis
*/
function initializeSitemapIssuesAnalysis() {
  const issuesList = document.getElementById('issuesList');
  if (!issuesList) return;

  // Clear loading indicator
  issuesList.innerHTML = '';

  // Check for various issues
  const issues = [];

  // Check if any sitemaps have failed
  const failedSitemaps = document.querySelectorAll('#sitemapsTable .badge.bg-danger');
  if (failedSitemaps.length > 0) {
      issues.push({
          severity: 'high',
          message: `${failedSitemaps.length} sitemap(s) failed to parse`,
          icon: 'exclamation-circle'
      });
  }

  // Check for missing priorities
  const totalUrls = document.querySelectorAll('#urlsTable tbody tr').length;
  const urlsWithPriority = getUrlsWithPriorityCount();
  if (urlsWithPriority / totalUrls < 0.5) {
      issues.push({
          severity: 'medium',
          message: 'Most URLs are missing priority values',
          icon: 'star'
      });
  }

  // Check for missing lastmod dates
  const urlsWithLastmod = getUrlsWithLastmodCount();
  if (urlsWithLastmod / totalUrls < 0.5) {
      issues.push({
          severity: 'medium',
          message: 'Most URLs are missing last modified dates',
          icon: 'calendar-alt'
      });
  }

  // Check for missing changefreq values
  const urlsWithChangefreq = getUrlsWithChangefreqCount();
  if (urlsWithChangefreq / totalUrls < 0.5) {
      issues.push({
          severity: 'low',
          message: 'Most URLs are missing change frequency values',
          icon: 'sync-alt'
      });
  }

  // Check for recently updated content
  const recentlyUpdatedCount = getRecentlyUpdatedCount();
  if (recentlyUpdatedCount / totalUrls < 0.1) {
      issues.push({
          severity: 'medium',
          message: 'Very few pages have been updated recently',
          icon: 'clock'
      });
  }

  // Check URL depth - too many deep URLs can be an issue
  const deepUrls = countDeepUrls();
  if (deepUrls / totalUrls > 0.3) {
      issues.push({
          severity: 'low',
          message: 'Many URLs have a deep directory structure',
          icon: 'sitemap'
      });
  }

  // Add issues to the list
  const severityClasses = {
      'high': 'danger',
      'medium': 'warning',
      'low': 'info'
  };

  if (issues.length === 0) {
      // No issues found
      issuesList.innerHTML = `
          <li class="list-group-item text-success">
              <i class="fas fa-check-circle me-2"></i>No significant issues detected
          </li>
      `;
  } else {
      // Sort issues by severity
      issues.sort((a, b) => {
          const severityOrder = { 'high': 0, 'medium': 1, 'low': 2 };
          return severityOrder[a.severity] - severityOrder[b.severity];
      });

      // Add issues to the list
      issues.forEach(issue => {
          const li = document.createElement('li');
          li.className = `list-group-item text-${severityClasses[issue.severity]}`;
          li.innerHTML = `<i class="fas fa-${issue.icon} me-2"></i>${issue.message}`;
          issuesList.appendChild(li);
      });
  }
}

/**
* Initialize URL Table with search and pagination
*/
function initializeURLTable() {
  const urlSearch = document.getElementById('urlSearch');
  const filterCrawlable = document.getElementById('filterCrawlable');
  const filterHighPriority = document.getElementById('filterHighPriority');
  const resetFilter = document.getElementById('resetFilter');
  const urlsTable = document.getElementById('urlsTable');
  const shownUrls = document.getElementById('shownUrls');
  const urlPagination = document.getElementById('urlPagination');

  if (!urlsTable || !urlSearch) return;

  const rows = Array.from(urlsTable.querySelectorAll('tbody tr'));
  let filteredRows = [...rows];
  const rowsPerPage = 20;
  let currentPage = 1;

  // Function to filter rows
  function filterRows() {
      const searchTerm = urlSearch.value.toLowerCase();

      filteredRows = rows.filter(row => {
          const url = row.querySelector('a').textContent.toLowerCase();
          const matchesSearch = url.includes(searchTerm);

          // Check for crawlable filter
          let matchesCrawlable = true;
          if (filterCrawlable.classList.contains('active')) {
              matchesCrawlable = !row.querySelector('a').href.match(/\.(pdf|docx?|xlsx?|pptx?|zip|rar|jpg|jpeg|png|gif|svg|webp|mp4|avi|mov|wmv)$/i);
          }

          // Check for high priority filter
          let matchesPriority = true;
          if (filterHighPriority.classList.contains('active')) {
              const priority = parseFloat(row.dataset.priority || 0);
              matchesPriority = priority >= 0.7;
          }

          return matchesSearch && matchesCrawlable && matchesPriority;
      });

      // Update shown count
      if (shownUrls) {
          shownUrls.textContent = filteredRows.length;
      }

      // Reset to first page
      currentPage = 1;

      // Update pagination and display rows
      updatePagination();
      displayRows();
  }

  // Function to update pagination
  function updatePagination() {
      if (!urlPagination) return;

      const totalPages = Math.ceil(filteredRows.length / rowsPerPage);
      urlPagination.innerHTML = '';

      // Add previous button
      const prevLi = document.createElement('li');
      prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
      prevLi.innerHTML = `<a class="page-link" href="#" aria-label="Previous">
          <span aria-hidden="true">&laquo;</span>
      </a>`;
      prevLi.addEventListener('click', (e) => {
          e.preventDefault();
          if (currentPage > 1) {
              currentPage--;
              updatePagination();
              displayRows();
          }
      });
      urlPagination.appendChild(prevLi);

      // Add page numbers (with ellipsis for large numbers)
      const maxVisiblePages = 5;
      let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
      let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

      if (endPage - startPage + 1 < maxVisiblePages) {
          startPage = Math.max(1, endPage - maxVisiblePages + 1);
      }

      if (startPage > 1) {
          // Add first page and ellipsis
          const firstLi = document.createElement('li');
          firstLi.className = 'page-item';
          firstLi.innerHTML = '<a class="page-link" href="#">1</a>';
          firstLi.addEventListener('click', (e) => {
              e.preventDefault();
              currentPage = 1;
              updatePagination();
              displayRows();
          });
          urlPagination.appendChild(firstLi);

          if (startPage > 2) {
              const ellipsisLi = document.createElement('li');
              ellipsisLi.className = 'page-item disabled';
              ellipsisLi.innerHTML = '<a class="page-link" href="#">...</a>';
              urlPagination.appendChild(ellipsisLi);
          }
      }

      for (let i = startPage; i <= endPage; i++) {
          const pageLi = document.createElement('li');
          pageLi.className = `page-item ${i === currentPage ? 'active' : ''}`;
          pageLi.innerHTML = `<a class="page-link" href="#">${i}</a>`;
          pageLi.addEventListener('click', (e) => {
              e.preventDefault();
              currentPage = i;
              updatePagination();
              displayRows();
          });
          urlPagination.appendChild(pageLi);
      }

      if (endPage < totalPages) {
          // Add ellipsis and last page
          if (endPage < totalPages - 1) {
              const ellipsisLi = document.createElement('li');
              ellipsisLi.className = 'page-item disabled';
              ellipsisLi.innerHTML = '<a class="page-link" href="#">...</a>';
              urlPagination.appendChild(ellipsisLi);
          }

          const lastLi = document.createElement('li');
          lastLi.className = 'page-item';
          lastLi.innerHTML = `<a class="page-link" href="#">${totalPages}</a>`;
          lastLi.addEventListener('click', (e) => {
              e.preventDefault();
              currentPage = totalPages;
              updatePagination();
              displayRows();
          });
          urlPagination.appendChild(lastLi);
      }

      // Add next button
      const nextLi = document.createElement('li');
      nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
      nextLi.innerHTML = `<a class="page-link" href="#" aria-label="Next">
          <span aria-hidden="true">&raquo;</span>
      </a>`;
      nextLi.addEventListener('click', (e) => {
          e.preventDefault();
          if (currentPage < totalPages) {
              currentPage++;
              updatePagination();
              displayRows();
          }
      });
      urlPagination.appendChild(nextLi);
  }

  // Function to display rows based on current page
  function displayRows() {
      const startIndex = (currentPage - 1) * rowsPerPage;
      const endIndex = startIndex + rowsPerPage;
      const visibleRows = filteredRows.slice(startIndex, endIndex);

      // Hide all rows
      rows.forEach(row => {
          row.style.display = 'none';
      });

      // Show visible rows
      visibleRows.forEach(row => {
          row.style.display = '';
      });
  }

  // Set up event listeners
  if (urlSearch) {
      urlSearch.addEventListener('input', filterRows);
  }

  if (filterCrawlable) {
      filterCrawlable.addEventListener('click', function() {
          this.classList.toggle('active');
          this.classList.toggle('btn-outline-secondary');
          this.classList.toggle('btn-secondary');
          filterRows();
      });
  }

  if (filterHighPriority) {
      filterHighPriority.addEventListener('click', function() {
          this.classList.toggle('active');
          this.classList.toggle('btn-outline-secondary');
          this.classList.toggle('btn-secondary');
          filterRows();
      });
  }

  if (resetFilter) {
      resetFilter.addEventListener('click', function() {
          urlSearch.value = '';
          filterCrawlable.classList.remove('active', 'btn-secondary');
          filterCrawlable.classList.add('btn-outline-secondary');
          filterHighPriority.classList.remove('active', 'btn-secondary');
          filterHighPriority.classList.add('btn-outline-secondary');
          filterRows();
      });
  }

  // Initialize pagination and display
  updatePagination();
  displayRows();
}

/**
* Initialize URL Depth Analysis
*/
function initializeDepthAnalysis() {
  const depthChart = document.getElementById('depthChart');
  const directoryTree = document.getElementById('directoryTree');

  if (!depthChart || !directoryTree) return;

  // Collect URL data
  const urls = [];
  document.querySelectorAll('#urlsTable tbody tr a').forEach(anchor => {
      urls.push(anchor.href);
  });

  // Analyze URL depths
  const depths = {};
  const tree = { name: 'root', children: {} };

  urls.forEach(url => {
      try {
          const urlObj = new URL(url);
          const path = urlObj.pathname;
          const segments = path.split('/').filter(Boolean);
          const depth = segments.length;

          // Count depths
          depths[depth] = (depths[depth] || 0) + 1;

          // Build tree structure
          let currentNode = tree;
          segments.forEach(segment => {
              if (!currentNode.children[segment]) {
                  currentNode.children[segment] = { name: segment, children: {}, count: 0 };
              }
              currentNode = currentNode.children[segment];
              currentNode.count++;
          });
      } catch (error) {
          console.error('Error parsing URL:', error);
      }
  });

  // Create depth chart
  new Chart(depthChart, {
      type: 'bar',
      data: {
          labels: Object.keys(depths).map(depth => `Depth ${depth}`),
          datasets: [{
              label: 'Number of URLs',
              data: Object.values(depths),
              backgroundColor: 'rgba(75, 192, 192, 0.6)',
              borderColor: 'rgba(75, 192, 192, 1)',
              borderWidth: 1
          }]
      },
      options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
              legend: {
                  display: false
              },
              tooltip: {
                  callbacks: {
                      label: function(context) {
                          return `${context.raw} URLs`;
                      }
                  }
              }
          },
          scales: {
              y: {
                  beginAtZero: true,
                  title: {
                      display: true,
                      text: 'Number of URLs'
                  }
              }
          }
      }
  });

  // Create directory tree visualization
  function renderTree(node, parentElement, isRoot = false) {
      const div = document.createElement('div');
      div.className = isRoot ? '' : 'ms-3 mt-2';

      if (!isRoot) {
          const folderIcon = document.createElement('i');
          folderIcon.className = 'fas fa-folder text-warning me-2';
          div.appendChild(folderIcon);

          const nameSpan = document.createElement('span');
          nameSpan.className = 'fw-bold';
          nameSpan.textContent = node.name;
          div.appendChild(nameSpan);

          if (node.count) {
              const countBadge = document.createElement('span');
              countBadge.className = 'badge bg-primary ms-2';
              countBadge.textContent = node.count;
              div.appendChild(countBadge);
          }
      }

      parentElement.appendChild(div);

      // Sort children by count (descending)
      const sortedChildren = Object.values(node.children).sort((a, b) => b.count - a.count);

      if (sortedChildren.length > 0) {
          const childrenDiv = document.createElement('div');
          childrenDiv.className = isRoot ? '' : 'border-start border-2 ms-2 ps-2 mt-1';
          div.appendChild(childrenDiv);

          sortedChildren.forEach(child => {
              renderTree(child, childrenDiv);
          });
      }
  }

  renderTree(tree, directoryTree, true);
}

/**
* Initialize Site Structure Visualization with D3.js
*/
function initializeSiteStructureVisualization() {
  const container = document.getElementById('siteStructureVisualization');
  if (!container) return;

  // Check if D3 is available
  if (typeof d3 === 'undefined') {
      // Load D3.js if not available
      const script = document.createElement('script');
      script.src = 'https://d3js.org/d3.v7.min.js';
      script.onload = createVisualization;
      document.head.appendChild(script);
  } else {
      createVisualization();
  }

  function createVisualization() {
      // Container for loading indicator
      container.innerHTML = '';
      const loadingDiv = document.createElement('div');
      loadingDiv.className = 'd-flex justify-content-center align-items-center h-100';
      loadingDiv.innerHTML = '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>';
      container.appendChild(loadingDiv);

      // Collect URL data
      const urls = [];
      document.querySelectorAll('#urlsTable tbody tr a').forEach(anchor => {
          urls.push(anchor.href);
      });

      // Process data for network visualization
      setTimeout(() => {
          try {
              // Create nodes and links
              const baseUrl = new URL(urls[0]).origin;
              const nodes = [{ id: 'root', name: baseUrl, group: 1 }];
              const links = [];
              const nodeMap = { 'root': 0 };
              let nodeIndex = 1;

              urls.forEach(url => {
                  try {
                      const urlObj = new URL(url);
                      const path = urlObj.pathname;
                      const segments = path.split('/').filter(Boolean);

                      let parentId = 'root';
                      let currentPath = '';

                      segments.forEach((segment, index) => {
                          currentPath += '/' + segment;
                          const segmentId = currentPath;

                          // Add node if it doesn't exist
                          if (!nodeMap.hasOwnProperty(segmentId)) {
                              nodeMap[segmentId] = nodeIndex++;
                              nodes.push({
                                  id: segmentId,
                                  name: segment,
                                  group: index + 2,
                                  isFile: index === segments.length - 1 && segment.includes('.')
                              });
                          }

                          // Add link from parent to this node
                          links.push({
                              source: nodeMap[parentId],
                              target: nodeMap[segmentId],
                              value: 1
                          });

                          parentId = segmentId;
                      });
                  } catch (error) {
                      console.error('Error processing URL for visualization:', error);
                  }
              });

              // Remove loading indicator
              container.innerHTML = '';

              // Set up the SVG
              const width = container.clientWidth;
              const height = container.clientHeight;

              const svg = d3.select(container)
                  .append('svg')
                  .attr('width', width)
                  .attr('height', height)
                  .attr('viewBox', [0, 0, width, height]);

              // Create a force simulation
              const simulation = d3.forceSimulation(nodes)
                  .force('link', d3.forceLink(links).id(d => d.id).distance(100))
                  .force('charge', d3.forceManyBody().strength(-300))
                  .force('center', d3.forceCenter(width / 2, height / 2))
                  .force('collision', d3.forceCollide().radius(30));

              // Create a group for links
              const link = svg.append('g')
                  .selectAll('line')
                  .data(links)
                  .join('line')
                  .attr('stroke', '#999')
                  .attr('stroke-opacity', 0.6)
                  .attr('stroke-width', d => Math.sqrt(d.value));

              // Create a group for nodes
              const node = svg.append('g')
                  .selectAll('g')
                  .data(nodes)
                  .join('g')
                  .call(drag(simulation));

              // Add circles to nodes
              node.append('circle')
                  .attr('r', d => d.id === 'root' ? 15 : (d.isFile ? 8 : 12))
                  .attr('fill', d => {
                      if (d.id === 'root') return '#3498db';
                      if (d.isFile) {
                          // Determine file type color
                          const name = d.name.toLowerCase();
                          if (name.match(/\.(pdf|docx?|xlsx?|pptx?|zip|rar)$/)) {
                              return '#e67e22'; // Document
                          } else if (name.match(/\.(jpg|jpeg|png|gif|svg|webp)$/)) {
                              return '#1abc9c'; // Image
                          } else if (name.match(/\.(mp4|avi|mov|wmv)$/)) {
                              return '#e74c3c'; // Video
                          } else {
                              return '#2ecc71'; // Web page
                          }
                      }
                      return '#9b59b6'; // Directory
                  })
                  .attr('stroke', '#fff')
                  .attr('stroke-width', 1.5);

              // Add labels to nodes
              node.append('text')
                  .attr('dx', 12)
                  .attr('dy', '.35em')
                  .attr('font-size', d => d.id === 'root' ? '12px' : '10px')
                  .text(d => d.name)
                  .style('pointer-events', 'none')
                  .each(function(d) {
                      const text = d3.select(this);
                      const words = d.name.split(/(?=[\/])|(?<=[\/])/g);

                      if (words.length > 1 && d.id !== 'root') {
                          text.text(null);
                          text.append('tspan')
                              .attr('x', 12)
                              .attr('dy', '0em')
                              .text(words.slice(0, 2).join(''));

                          if (words.length > 2) {
                              text.append('tspan')
                                  .attr('x', 12)
                                  .attr('dy', '1.2em')
                                  .text('...');
                          }
                      }
                  });

              // Add title for hover
              node.append('title')
                  .text(d => d.id);

              // Update positions on simulation tick
              simulation.on('tick', () => {
                  link
                      .attr('x1', d => d.source.x)
                      .attr('y1', d => d.source.y)
                      .attr('x2', d => d.target.x)
                      .attr('y2', d => d.target.y);

                  node.attr('transform', d => `translate(${d.x},${d.y})`);
              });

              // Add zoom functionality
              const zoom = d3.zoom()
                  .scaleExtent([0.1, 4])
                  .on('zoom', (event) => {
                      svg.selectAll('g').attr('transform', event.transform);
                  });

              svg.call(zoom);

              // Add zoom controls
              const zoomControls = d3.select(container)
                  .append('div')
                  .attr('class', 'position-absolute bottom-0 end-0 p-2')
                  .html(`
                      <div class="btn-group">
                          <button class="btn btn-sm btn-light" id="zoomIn">
                              <i class="fas fa-search-plus"></i>
                          </button>
                          <button class="btn btn-sm btn-light" id="zoomOut">
                              <i class="fas fa-search-minus"></i>
                          </button>
                          <button class="btn btn-sm btn-light" id="resetZoom">
                              <i class="fas fa-sync-alt"></i>
                          </button>
                      </div>
                  `);

              // Add event listeners for zoom controls
              document.getElementById('zoomIn').addEventListener('click', () => {
                  svg.transition().call(zoom.scaleBy, 1.3);
              });

              document.getElementById('zoomOut').addEventListener('click', () => {
                  svg.transition().call(zoom.scaleBy, 0.7);
              });

              document.getElementById('resetZoom').addEventListener('click', () => {
                  svg.transition().call(zoom.transform, d3.zoomIdentity);
              });
          } catch (error) {
              console.error('Error creating visualization:', error);
              container.innerHTML = `
                  <div class="alert alert-warning">
                      <i class="fas fa-exclamation-triangle me-2"></i>
                      Unable to create visualization. Please try again later.
                  </div>
              `;
          }
      }, 500); // Small delay to allow the UI to show loading indicator
  }

  // Function to implement drag behavior
  function drag(simulation) {
      function dragstarted(event) {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          event.subject.fx = event.subject.x;
          event.subject.fy = event.subject.y;
      }

      function dragged(event) {
          event.subject.fx = event.x;
          event.subject.fy = event.y;
      }

      function dragended(event) {
          if (!event.active) simulation.alphaTarget(0);
          event.subject.fx = null;
          event.subject.fy = null;
      }

      return d3.drag()
          .on("start", dragstarted)
          .on("drag", dragged)
          .on("end", dragended);
  }
}

document.addEventListener('DOMContentLoaded', function() {
    // Select URL input fields across different pages
    const urlInputs = document.querySelectorAll('input[name="url"][type="url"]');

    urlInputs.forEach(function(urlInput) {
        // Function to normalize URL input
        function normalizeUrlInput() {
            let value = urlInput.value.trim();

            // Remove 'https://' if it exists
            value = value.replace(/^https?:\/\//, '');

            // Remove any leading or trailing whitespace
            value = value.trim();

            // Prepend 'https://'
            urlInput.value = 'https://' + value;
        }

        // Add event listeners to normalize input
        urlInput.addEventListener('blur', normalizeUrlInput);
        urlInput.addEventListener('change', normalizeUrlInput);

        // Initial normalization
        normalizeUrlInput();

        // Optional: Auto-select text when focused if it's just 'https://'
        urlInput.addEventListener('focus', function() {
            if (this.value === 'https://') {
                this.select();
            }
        });
    });
});
