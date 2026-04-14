// MariNet main JavaScript file

document.addEventListener('DOMContentLoaded', function() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    const flashMessages = document.querySelectorAll('.alert-dismissible');
    flashMessages.forEach(function(message) {
        setTimeout(function() {
            const closeButton = message.querySelector('.btn-close');
            if (closeButton) {
                closeButton.click();
            }
        }, 5000);
    });
    
    function checkUnreadNotifications() {
        const notificationsLink = document.querySelector('a[href*="notifications"]');
        if (!notificationsLink) {
            console.error('Notifications link not found in the DOM');
            return;
        }
        
        console.log('Checking for unread notifications...');
        fetch('/api/unread-notifications-count')
            .then(response => response.json())
            .then(data => {
                const count = data.count;
                console.log('Unread notifications:', count);
                const existingBadge = notificationsLink.querySelector('.notification-badge');
                
                if (count > 0) {
                    if (existingBadge) {
                        console.log('Updating existing badge:', count);
                        existingBadge.textContent = count;
                    } else {
                        console.log('Creating new badge:', count);
                        const badge = document.createElement('span');
                        badge.className = 'badge bg-danger notification-badge';
                        badge.textContent = count;
                        notificationsLink.appendChild(badge);
                    }
                } else if (existingBadge) {
                    console.log('Removing badge - no unread notifications');
                    existingBadge.remove();
                }
            })
            .catch(error => console.error('Error fetching notification count:', error));
    }
    
    if (document.querySelector('a[href*="notifications"]')) {
        checkUnreadNotifications();
        setInterval(checkUnreadNotifications, 30000);
    }
    
    function checkVoteStatus() {
        const voteBtns = document.querySelectorAll('.vote-btn');
        if (voteBtns.length === 0) return;
        
        fetch('/api/user-votes')
            .then(response => response.json())
            .then(data => {
                voteBtns.forEach(btn => {
                    const postId = btn.dataset.postId;
                    const voteType = btn.dataset.voteType;
                    
                    if (data.votes[postId] === voteType) {
                        btn.classList.add(voteType === 'upvote' ? 'active-upvote' : 'active-downvote');
                    }
                });
            })
            .catch(error => console.error('Error fetching votes:', error));
    }
    
    if (document.querySelector('.vote-btn')) {
        checkVoteStatus();
    }
    
    function formatRelativeTime() {
        const dateElements = document.querySelectorAll('.relative-time');
        
        dateElements.forEach(element => {
            const timestamp = new Date(element.dataset.timestamp);
            const now = new Date();
            const diffMs = now - timestamp;
            const diffSec = Math.floor(diffMs / 1000);
            const diffMin = Math.floor(diffSec / 60);
            const diffHour = Math.floor(diffMin / 60);
            const diffDay = Math.floor(diffHour / 24);
            
            let relativeTime;
            
            if (diffDay > 30) {
                relativeTime = timestamp.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: now.getFullYear() !== timestamp.getFullYear() ? 'numeric' : undefined
                });
            } else if (diffDay > 0) {
                relativeTime = `${diffDay}d ago`;
            } else if (diffHour > 0) {
                relativeTime = `${diffHour}h ago`;
            } else if (diffMin > 0) {
                relativeTime = `${diffMin}m ago`;
            } else {
                relativeTime = 'Just now';
            }
            
            element.textContent = relativeTime;
        });
    }
    
    formatRelativeTime();
});

function previewImage(inputId, imgId) {
    const input = document.getElementById(inputId);
    const imgPreview = document.getElementById(imgId);
    
    if (!input || !imgPreview) return;
    
    input.addEventListener('change', function() {
        if (this.files && this.files[0]) {
            const reader = new FileReader();
            
            reader.onload = function(e) {
                imgPreview.src = e.target.result;
                imgPreview.style.display = 'block';
            };
            
            reader.readAsDataURL(this.files[0]);
        }
    });
} 

