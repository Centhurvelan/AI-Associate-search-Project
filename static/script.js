// static/script.js - Modified to handle tabular output, show count, and add serial number
document.addEventListener('DOMContentLoaded', (event) => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const newChatButton = document.getElementById('new-chat-button');

    // Function to display a message in the chat box
    function displayMessage(sender, content) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message');

        // Create a wrapper for message content (NL text + count + table)
        const contentElement = document.createElement('div');
        contentElement.classList.add('message-content');

        if (sender === 'User') {
            messageElement.classList.add('user-message');
            contentElement.textContent = content; // Content is just the user's string input
            messageElement.appendChild(contentElement);
        } else if (sender === 'AI') {
            messageElement.classList.add('ai-message');
            // Content for AI is assumed to be the data object from the backend
            let nlResponse = "";
            let columnNames = [];
            let results = [];
            let generatedSql = ""; // Added to display generated SQL
            let error = null; // Added to display errors from backend

            // Check if content is the expected object structure
            if (typeof content === 'object' && content !== null) {
                nlResponse = content.natural_language_response || "";
                columnNames = content.column_names || [];
                results = content.results || [];
                generatedSql = content.generated_sql || ""; // Populate generated SQL
                error = content.error || null; // Populate error
            } else {
                nlResponse = String(content); // Ensure it's treated as a string for backward compatibility
            }

            // Display Natural Language Response first if it exists
            if (nlResponse) {
                const nlElement = document.createElement('p');
                nlElement.classList.add('nl-response');
                nlElement.innerHTML = nlResponse.replace(/\n/g, '<br>'); // Preserve line breaks
                contentElement.appendChild(nlElement);
            }

            // Display generated SQL if it exists
            if (generatedSql) {
                const sqlElement = document.createElement('p');
                sqlElement.classList.add('generated-sql');
                sqlElement.innerHTML = `SQL Generated: <code>${generatedSql}</code>`;
                contentElement.appendChild(sqlElement);
            }

            // Display the count of results if results exist
            if (results.length > 0) {
                const countElement = document.createElement('p');
                countElement.classList.add('results-count');
                countElement.textContent = `Showing ${results.length} rows:`;
                contentElement.appendChild(countElement);
            }

            // Display Data Table if results exist and there are columns
            if (results.length > 0 && columnNames.length > 0) {
                const tableContainer = document.createElement('div');
                tableContainer.classList.add('results-table-container');

                const tableElement = document.createElement('table');
                tableElement.classList.add('results-table');
                // Create table header
                const thead = document.createElement('thead');
                const headerRow = document.createElement('tr');

                // Add Serial Number header
                const snHeader = document.createElement('th');
                snHeader.textContent = 'S.No.';
                headerRow.appendChild(snHeader);

                // Add other column headers
                columnNames.forEach(colName => {
                    const th = document.createElement('th');
                    th.textContent = colName;
                    headerRow.appendChild(th);
                });
                thead.appendChild(headerRow);
                tableElement.appendChild(thead);
                // Create table body
                const tbody = document.createElement('tbody');
                tableElement.appendChild(tbody);
                // Pagination variables
                const rowsPerPage = 30;
                let currentPage = 1;
                const pageCount = Math.ceil(results.length / rowsPerPage);

                // Function to render table rows
                function renderTableRows(page) {
                    tbody.innerHTML = "";
                    const start = (page - 1) * rowsPerPage;
                    const end = Math.min(start + rowsPerPage, results.length);
                    for (let i = start; i < end; i++) {
                        const rowData = results[i];
                        const dataRow = document.createElement('tr');
                        // Add Serial Number cell
                        const snCell = document.createElement('td');
                        snCell.textContent = i + 1; // Serial number for current row
                        dataRow.appendChild(snCell);
                        rowData.forEach(cellData => {
                            const td = document.createElement('td');
                            // Handle potential null values
                            td.textContent = cellData !== null ? String(cellData) : 'NULL';
                            dataRow.appendChild(td);
                        });
                        tbody.appendChild(dataRow);
                    }
                }

                // Function to render pagination controls
                function renderPagination() {
                    const pagination = document.createElement('div');
                    pagination.classList.add('pagination');
                    const prevButton = document.createElement('button');
                    prevButton.classList.add('pagination-button');
                    prevButton.textContent = 'Previous';
                    prevButton.disabled = currentPage === 1;
                    prevButton.addEventListener('click', () => {
                        if (currentPage > 1) {
                            currentPage--;
                            renderTableRows(currentPage);
                            updatePagination();
                        }
                    });
                    pagination.appendChild(prevButton);
                    const pageDisplay = document.createElement('span');
                    pageDisplay.classList.add('page-number');
                    pageDisplay.textContent = `Page ${currentPage} of ${pageCount}`;
                    pagination.appendChild(pageDisplay);
                    const pageNumberInput = document.createElement('input');
                    pageNumberInput.type = 'number';
                    pageNumberInput.classList.add('page-input');
                    pageNumberInput.min = 1;
                    pageNumberInput.max = pageCount;
                    pageNumberInput.placeholder = 'Page';
                    pagination.appendChild(pageNumberInput);
                    const goToPageButton = document.createElement('button');
                    goToPageButton.classList.add('pagination-button');
                    goToPageButton.textContent = 'Go';
                    goToPageButton.addEventListener('click', () => {
                        const pageNumber = parseInt(pageNumberInput.value);
                        if (!isNaN(pageNumber) && pageNumber >= 1 && pageNumber <= pageCount) {
                            currentPage = pageNumber;
                            renderTableRows(currentPage);
                            updatePagination();
                        }
                    });
                    pagination.appendChild(goToPageButton);
                    const nextButton = document.createElement('button');
                    nextButton.classList.add('pagination-button');
                    nextButton.textContent = 'Next';
                    nextButton.disabled = currentPage === pageCount;
                    nextButton.addEventListener('click', () => {
                        if (currentPage < pageCount) {
                            currentPage++;
                            renderTableRows(currentPage);
                            updatePagination();
                        }
                    });
                    pagination.appendChild(nextButton);
                    return pagination;
                }

                // Function to update pagination controls
                function updatePagination() {
                    const pagination = contentElement.querySelector('.pagination');
                    // Ensure elements exist before querying them
                    if (!pagination) return;
                    const prevButton = pagination.querySelector('.pagination-button:first-of-type');
                    const pageDisplay = pagination.querySelector('.page-number');
                    const pageNumberInput = pagination.querySelector('.page-input');
                    const nextButton = pagination.querySelector('.pagination-button:last-of-type');

                    if (prevButton) prevButton.disabled = currentPage === 1;
                    if (nextButton) nextButton.disabled = currentPage === pageCount;
                    if (pageDisplay) pageDisplay.textContent = `Page ${currentPage} of ${pageCount}`;
                    if (pageNumberInput) pageNumberInput.value = ''; // Clear the input field
                }

                // Append table and initial pagination to the content wrapper
                tableContainer.appendChild(tableElement);
                contentElement.appendChild(tableContainer);
                if (pageCount > 1) { // Only render pagination if more than one page
                    contentElement.appendChild(renderPagination()); // Render pagination controls
                }
                renderTableRows(currentPage); // Initial table rendering
            } else if (nlResponse && (nlResponse.includes("returned no results") || nlResponse.includes("no data"))) {
                // Optionally handle explicit "no results" messages by AI, or rely on AI's summary
            } else if (results.length === 0 && columnNames.length > 0) {
                // Explicitly handle queries that return 0 rows without an explicit NL message from AI
                const noResultsElement = document.createElement('p');
                noResultsElement.classList.add('no-results-message');
                noResultsElement.textContent = "Query executed, but returned no data.";
                contentElement.appendChild(noResultsElement);
            }
            // Display error if present
            if (error) {
                const errorElement = document.createElement('p');
                errorElement.classList.add('error-message');
                errorElement.textContent = `Error: ${error}`;
                contentElement.appendChild(errorElement);
            }

            // Append the content wrapper to the message element
            messageElement.appendChild(contentElement);
        } else if (sender === 'System') {
            messageElement.classList.add('system-message');
            contentElement.textContent = content;
            messageElement.appendChild(contentElement);
        }
        chatBox.appendChild(messageElement);
        chatBox.scrollTop = chatBox.scrollHeight; // Scroll to the bottom
    }

    // Initial message on load
    displayMessage('System', "I'm your dedicated AI assistant, ready to help you find associate details.");

    // Handle form submission (Send button)
    chatForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const query = userInput.value.trim();
        if (!query) {
            return;
        }

        // Display user's message immediately
        displayMessage('User', query);
        userInput.value = '';

        // Display a "Loading..." message
        displayMessage('System', 'Loading...');

        // Send the query to the backend
        fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: query }),
        })
        .then(response => {
            if (!response.ok) {
                // Parse error message from backend if available
                return response.json().then(err => {
                    // Assuming FastAPI error returns {"detail": "message"}
                    throw new Error(`Backend error: ${response.status} ${response.statusText} - ${err.detail || 'Unknown error'}`);
                }).catch(() => {
                    // Fallback if error response is not JSON or unexpected format
                    throw new Error(`Backend error: ${response.status} ${response.statusText}`);
                });
            }
            return response.json();
        })
        .then(data => {
            // Remove the "Loading..." message
            const thinkingMessage = chatBox.querySelector('.system-message:last-child');
            if (thinkingMessage && thinkingMessage.textContent === 'Loading...') {
                chatBox.removeChild(thinkingMessage);
            }
            displayMessage('AI', data); // Pass the full data object to displayMessage
        })
        .catch((error) => {
            console.error('Error:', error);
            // Remove the "Loading..." message even on error
            const thinkingMessage = chatBox.querySelector('.system-message:last-child');
            if (thinkingMessage && thinkingMessage.textContent === 'Loading...') {
                chatBox.removeChild(thinkingMessage);
            }
            displayMessage('System', `Sorry, an error occurred: ${error.message || error}`);
        });
    });

    // Handle New Chat button click
    newChatButton.addEventListener('click', () => {
        if (confirm("Are you sure you want to start a new chat? This will clear the conversation history.")) {
            fetch('/new_chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({}),
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw new Error(`Backend error: ${response.status} ${response.statusText} - ${err.detail || 'Unknown error'}`);
                    }).catch(() => {
                        throw new Error(`Backend error: ${response.status} ${response.statusText}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    chatBox.innerHTML = '';
                    displayMessage('System', 'New chat started. How can I help you with the data?');
                } else {
                    displayMessage('System', 'Error starting new chat: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error starting new chat:', error);
                displayMessage('System', 'Sorry, an error occurred while trying to start a new chat.');
            });
        }
    });
});